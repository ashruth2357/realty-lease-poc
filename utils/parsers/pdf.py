import io
import sys
from typing import Any, List, Dict, Tuple, Optional, Union
from dataclasses import dataclass
import fitz  # PyMuPDF


@dataclass
class PDFChunk:
    """Represents a chunk of PDF content with associated metadata."""
    page_number: int
    chunk_id: int
    overlap_info: Dict[str, Any]
    original_page_text: str  # Store the original page text without overlaps
    previous_overlap: Optional[str] = None  # Overlap text from previous chunk
    next_overlap: Optional[str] = None  # Overlap text from next chunk


class PDFChunker:
    """Main class for parsing and chunking PDF files."""
    
    def __init__(self, overlap_percentage: float = 0.2):
        """
        Initialize the PDF chunker.
        
        Args:
            overlap_percentage (float): Percentage of overlap between chunks (default: 0.2 for 20%)
        """
        self.overlap_percentage = overlap_percentage
        
    def parse_pdf(self, pdf_source: Union[str, bytes, io.BytesIO], extract_tables: bool = True) -> List[Tuple[int, str]]:
        """
        Parse a PDF file and extract text with page references.
        
        Args:
            pdf_source: Can be:
                - str: Path to the PDF file
                - bytes: PDF file content as bytes
                - io.BytesIO: PDF file as BytesIO object
            extract_tables (bool): Whether to extract tables with proper formatting
            
        Returns:
            List[Tuple[int, str]]: List of tuples containing (page_number, text)
            
        Raises:
            ValueError: If the PDF source is invalid
            Exception: If there's an error parsing the PDF
        """
        try:
            # Handle different input types
            if isinstance(pdf_source, str):
                # File path
                doc = fitz.open(pdf_source)
            elif isinstance(pdf_source, bytes):
                # Bytes data
                doc = fitz.open(stream=pdf_source, filetype="pdf")
            elif isinstance(pdf_source, io.BytesIO):
                # BytesIO object
                doc = fitz.open(stream=pdf_source.read(), filetype="pdf")
            else:
                raise ValueError(f"Unsupported PDF source type: {type(pdf_source)}")
            
            pages_data = []
            
            if extract_tables:
                # First pass: analyze all tables across pages to handle multi-page tables
                table_tracker = self._analyze_multi_page_tables(doc)
                
                # Second pass: extract text with table awareness
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    text = self._extract_text_with_tables_and_tracking(page, page_num + 1, table_tracker)
                    pages_data.append((page_num + 1, text))  # Page numbers start from 1
            else:
                # Basic text extraction
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    text = page.get_text()
                    pages_data.append((page_num + 1, text))  # Page numbers start from 1
                
            doc.close()
            return pages_data
            
        except Exception as e:
            raise Exception(f"Error parsing PDF: {str(e)}")
    
    def _analyze_multi_page_tables(self, doc) -> Dict:
        """
        Analyze tables across all pages to identify multi-page tables.
        
        Args:
            doc: PyMuPDF document object
            
        Returns:
            Dict: Table tracking information
        """
        table_tracker = {
            'multi_page_tables': {},  # Track tables that span multiple pages
            'table_origins': {},      # Track which page each table originates from
            'processed_tables': set() # Track which tables have been processed
        }
        
        try:
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                tables = page.find_tables()
                
                for i, table_obj in enumerate(tables):
                    table_id = f"page_{page_num + 1}_table_{i + 1}"
                    bbox = table_obj.bbox
                    
                    # Check if table extends beyond page boundaries
                    page_height = page.rect.height
                    if bbox[3] > page_height * 0.9:  # Table extends near bottom of page
                        # This might be a multi-page table
                        table_tracker['multi_page_tables'][table_id] = {
                            'origin_page': page_num + 1,
                            'bbox': bbox,
                            'table_obj': table_obj
                        }
                    
                    table_tracker['table_origins'][table_id] = page_num + 1
                    
        except Exception as e:
            print(f"Warning: Error analyzing multi-page tables: {str(e)}")
            
        return table_tracker
    
    def _extract_text_with_tables_and_tracking(self, page, page_num: int, table_tracker: Dict) -> str:
        """
        Extract text from a page with table awareness and multi-page table tracking.
        
        Args:
            page: PyMuPDF page object
            page_num (int): Page number
            table_tracker (Dict): Table tracking information
            
        Returns:
            str: Formatted text with tables properly structured
        """
        try:
            # Get basic text first
            basic_text = page.get_text()
            
            # Find tables on the page
            tables = page.find_tables()
            
            if not tables:
                return basic_text
            
            # Process tables with multi-page awareness
            result_text = basic_text
            
            for i, table_obj in enumerate(tables):
                table_id = f"page_{page_num}_table_{i + 1}"
                
                # Check if this table should be processed on this page
                if table_id in table_tracker['processed_tables']:
                    continue  # Skip if already processed
                
                # Check if this is a multi-page table
                if table_id in table_tracker['multi_page_tables']:
                    # This is a multi-page table - only show on origin page
                    if table_tracker['multi_page_tables'][table_id]['origin_page'] == page_num:
                        # This is the origin page - show the full table
                        table_data = table_obj.extract()
                        if table_data and len(table_data) > 0:
                            formatted_table = self._format_table_as_llm_friendly_text(table_data, i + 1)
                            result_text += f"\n\n{formatted_table}\n"
                            table_tracker['processed_tables'].add(table_id)
                    else:
                        # This is a continuation page - skip the table
                        table_tracker['processed_tables'].add(table_id)
                        continue
                else:
                    # Regular single-page table
                    table_data = table_obj.extract()
                    if table_data and len(table_data) > 0:
                        formatted_table = self._format_table_as_llm_friendly_text(table_data, i + 1)
                        result_text += f"\n\n{formatted_table}\n"
                        table_tracker['processed_tables'].add(table_id)
            
            return result_text
            
        except Exception as e:
            print(f"Warning: Table extraction failed, using basic text: {str(e)}")
            return page.get_text()
    
    def _format_table_as_llm_friendly_text(self, table_data: List[List[str]], table_num: int) -> str:
        """
        Format table data as LLM-friendly structured text.
        
        Args:
            table_data (List[List[str]]): Table data as list of rows
            table_num (int): Table number for reference
            
        Returns:
            str: LLM-friendly formatted table text
        """
        if not table_data or len(table_data) == 0:
            return f"TABLE {table_num}: [Empty table]"
        
        try:
            formatted_lines = []
            formatted_lines.append(f"TABLE {table_num}:")
            formatted_lines.append("=" * 50)
            
            # Process header row
            if len(table_data) > 0:
                header_row = table_data[0]
                formatted_lines.append("HEADER:")
                formatted_lines.append(" | ".join(str(cell).strip() if cell else "[Empty]" for cell in header_row))
                formatted_lines.append("-" * 60)
            
            # Process data rows
            if len(table_data) > 1:
                formatted_lines.append("DATA:")
                for row_idx, row in enumerate(table_data[1:], 1):
                    formatted_lines.append(f"Row {row_idx}: " + " | ".join(str(cell).strip() if cell else "[Empty]" for cell in row))
            
            formatted_lines.append("=" * 50)
            formatted_lines.append(f"END TABLE {table_num}")
            
            return "\n".join(formatted_lines)
            
        except Exception as e:
            return f"TABLE {table_num}: [Error formatting: {str(e)}]"
    
    def calculate_overlap_chars(self, text: str) -> int:
        """
        Calculate the number of characters to use for overlap.
        
        Args:
            text (str): The text to calculate overlap for
            
        Returns:
            int: Number of characters for overlap
        """
        return int(len(text) * self.overlap_percentage)
    
    def create_chunks(self, pages_data: List[Tuple[int, str]]) -> List[PDFChunk]:
        """
        Create chunks from pages data with overlap between adjacent pages.
        
        Args:
            pages_data (List[Tuple[int, str]]): List of (page_number, text) tuples
            
        Returns:
            List[PDFChunk]: List of PDF chunks with overlap information
        """
        if not pages_data:
            return []
            
        chunks = []
        total_pages = len(pages_data)
        
        for i, (page_num, text) in enumerate(pages_data):
            chunk_text = text
            overlap_info = {
                'has_previous_overlap': False,
                'has_next_overlap': False,
                'previous_page': None,
                'next_page': None,
                'overlap_chars_used': 0
            }
            
            # Initialize overlap text fields
            prev_overlap_text = None
            next_overlap_text = None
            
            # Add overlap from previous page (if not first page)
            if i > 0:
                prev_page_num, prev_text = pages_data[i - 1]
                overlap_chars = self.calculate_overlap_chars(prev_text)
                if overlap_chars > 0:
                    prev_overlap_text = prev_text[-overlap_chars:] if len(prev_text) > overlap_chars else prev_text
                    overlap_info['has_previous_overlap'] = True
                    overlap_info['previous_page'] = prev_page_num
                    overlap_info['overlap_chars_used'] += overlap_chars
            
            # Add overlap from next page (if not last page)
            if i < total_pages - 1:
                next_page_num, next_text = pages_data[i + 1]
                overlap_chars = self.calculate_overlap_chars(next_text)
                if overlap_chars > 0:
                    next_overlap_text = next_text[:overlap_chars] if len(next_text) > overlap_chars else next_text
                    overlap_info['has_next_overlap'] = True
                    overlap_info['next_page'] = next_page_num
                    overlap_info['overlap_chars_used'] += overlap_chars
            
            chunk = PDFChunk(
                page_number=page_num,
                chunk_id=i + 1,
                overlap_info=overlap_info,
                original_page_text=text,
                previous_overlap=prev_overlap_text,
                next_overlap=next_overlap_text
            )
            chunks.append(chunk)
            
        return chunks
    
    def process_pdf(self, pdf_source: Union[str, bytes, io.BytesIO], extract_tables: bool = True) -> List[PDFChunk]:
        """
        Main method to process a PDF file and return chunks.
        
        Args:
            pdf_source: Can be:
                - str: Path to the PDF file
                - bytes: PDF file content as bytes
                - io.BytesIO: PDF file as BytesIO object
            extract_tables (bool): Whether to extract tables with proper formatting
            
        Returns:
            List[PDFChunk]: List of PDF chunks with overlap
        """
        source_type = "file path" if isinstance(pdf_source, str) else "multipart data"
        print(f"Processing PDF from {source_type}")
        print(f"Table extraction: {'Enabled' if extract_tables else 'Disabled'}")
        
        # Parse the PDF
        pages_data = self.parse_pdf(pdf_source, extract_tables=extract_tables)
        print(f"Extracted text from {len(pages_data)} pages")
        
        # Create chunks with overlap
        chunks = self.create_chunks(pages_data)
        print(f"Created {len(chunks)} chunks with {self.overlap_percentage*100}% overlap")
        
        return chunks
    
    def get_table_info(self, pdf_source: Union[str, bytes, io.BytesIO]) -> Dict[int, int]:
        """
        Get information about tables found in the PDF.
        
        Args:
            pdf_source: Can be:
                - str: Path to the PDF file
                - bytes: PDF file content as bytes
                - io.BytesIO: PDF file as BytesIO object
            
        Returns:
            Dict[int, int]: Dictionary mapping page numbers to number of tables found
        """
        try:
            # Handle different input types
            if isinstance(pdf_source, str):
                doc = fitz.open(pdf_source)
            elif isinstance(pdf_source, bytes):
                doc = fitz.open(stream=pdf_source, filetype="pdf")
            elif isinstance(pdf_source, io.BytesIO):
                doc = fitz.open(stream=pdf_source.read(), filetype="pdf")
            else:
                raise ValueError(f"Unsupported PDF source type: {type(pdf_source)}")
            
            table_info = {}
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                tables = page.find_tables()
                table_list = list(tables)
                table_info[page_num + 1] = len(table_list)
                
            doc.close()
            return table_info
            
        except Exception as e:
            raise Exception(f"Error analyzing tables in PDF: {str(e)}")
    
    def print_chunk_summary(self, chunks: List[PDFChunk]):
        """
        Print a summary of the created chunks.
        
        Args:
            chunks (List[PDFChunk]): List of PDF chunks
        """
        print("\n" + "="*60)
        print("CHUNK SUMMARY")
        print("="*60)
        
        for chunk in chunks:
            table_count = chunk.original_page_text.count('TABLE ')
            
            print(f"\nChunk {chunk.chunk_id} (Page {chunk.page_number}):")
            print(f"  Text length: {len(chunk.original_page_text)} characters")
            print(f"  Tables found: {table_count}")
            print(f"  Overlap info: {chunk.overlap_info}")
            
            preview = chunk.original_page_text[:200] + "..." if len(chunk.original_page_text) > 200 else chunk.original_page_text
            print(f"  Text preview: {preview}")
            print("-" * 40)


# FastAPI Integration Example
"""
Example FastAPI endpoint usage:

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI()

@app.post("/upload-pdf/")
async def upload_pdf(file: UploadFile = File(...), extract_tables: bool = True):
    '''
    Upload a PDF file and get chunks with overlap.
    
    Args:
        file: PDF file uploaded via multipart/form-data
        extract_tables: Whether to extract tables (default: True)
    
    Returns:
        JSON with chunks information
    '''
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    try:
        # Read the file content
        pdf_content = await file.read()
        
        # Create chunker instance
        chunker = PDFChunker(overlap_percentage=0.2)
        
        # Process the PDF from bytes
        chunks = chunker.process_pdf(pdf_content, extract_tables=extract_tables)
        
        # Convert chunks to JSON-serializable format
        chunks_data = []
        for chunk in chunks:
            chunks_data.append({
                "chunk_id": chunk.chunk_id,
                "page_number": chunk.page_number,
                "text": chunk.original_page_text,
                "previous_overlap": chunk.previous_overlap,
                "next_overlap": chunk.next_overlap,
                "overlap_info": chunk.overlap_info
            })
        
        return JSONResponse(content={
            "status": "success",
            "total_chunks": len(chunks_data),
            "chunks": chunks_data
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")

@app.post("/pdf-table-info/")
async def get_pdf_table_info(file: UploadFile = File(...)):
    '''Get table information from PDF.'''
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    try:
        pdf_content = await file.read()
        chunker = PDFChunker()
        table_info = chunker.get_table_info(pdf_content)
        
        return JSONResponse(content={
            "status": "success",
            "table_info": table_info
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing PDF: {str(e)}")
"""


def main():
    """Example usage of the PDFChunker class with file path."""
    
    pdf_path = "/Users/vivek.singh/realty-poc/data/Bayer 2015-10-05 Lease.pdf"
    
    try:
        chunker = PDFChunker(overlap_percentage=0.2)
        chunks = chunker.process_pdf(pdf_path)
        chunker.print_chunk_summary(chunks)
        return chunks
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()