import base64
import re
import json 
import os 
from http import HTTPStatus
from fastapi import (
    APIRouter,
    File,
    UploadFile,
)
from dotenv import load_dotenv
from fastapi.responses import JSONResponse
from utils.logs import logger
from utils.helpers import get_llm_adapter, update_result_json
from utils.parsers.pdf import PDFChunker
from utils.prompts import LEASE_ANALYSIS
from utils.prompts import AMENDMENT_ANALYSIS
load_dotenv()
router = APIRouter()

llm_adapter = get_llm_adapter()

@router.post("")
async def get_lease_abstraction(
    assets: UploadFile | None = File(None)
):
    try:
        if not assets:
            return JSONResponse(
                content={"error": {"asset": "is invalid"}}, status_code=HTTPStatus.BAD_REQUEST.value
            )
        
        chunker = PDFChunker(overlap_percentage=0.2)
        
        # Process the PDF from bytes
        chunks = chunker.process_pdf(await assets.read(), extract_tables=True)
        
        # Convert chunks to JSON-serializable format
        chunks_data = []
        lease = {}
        for chunk in chunks:
            chunks_data.append({
                "chunk_id": chunk.chunk_id,
                "page_number": chunk.page_number,
                "text": chunk.original_page_text,
                "previous_overlap": chunk.previous_overlap,
                "next_overlap": chunk.next_overlap,
                "overlap_info": chunk.overlap_info
            })
            
            print(chunk)
            
            payload = [
                {
                    "role": "system", "content": "" # will be filled by Ashruth 
                },
                {
                    "role": "user", "content": ""
                }
            ]
            
            iterative_response = llm_adapter.get_non_streaming_response(payload)
            lease = update_result_json(lease, iterative_response)
            
        return lease 


        
    except Exception as error:
        logger.error(error)
        return JSONResponse(
                content={
                    "message": "Something went wrong, please contact support@stealth.com"
                }, status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value
            )
    


@router.post("/amendment-analysis")
async def amendment_analysis(
    amendment: UploadFile | None = File(None)
):
    try:
        # step 1: accept multipart pdf named 'amendment'
        if not amendment:
            return JSONResponse(
                content={"error": {"asset": "is invalid"}}, status_code=HTTPStatus.BAD_REQUEST.value
            )

        # step 2: compare amendment filename to existing fileid directories
        original_filename = amendment.filename or "uploaded_file.pdf"
        base_name = os.path.splitext(os.path.basename(original_filename))[0]

        # First try name-only matching: extract leading alphabetic name (e.g., "Bayer")
        name_match = re.match(r"\s*([A-Za-z]+)", base_name or "")
        candidate_dir = None
        candidate_fileid = None
        if name_match:
            name_key = name_match.group(1).lower()
            try:
                dirs = [d for d in os.listdir(".") if os.path.isdir(os.path.join(".", d))]
                # Prefer directories starting with the name; fallback to containing the name
                starts_with = [d for d in dirs if d.lower().startswith(name_key)]
                contains = [d for d in dirs if (name_key in d.lower())]
                chosen = starts_with[0] if starts_with else (contains[0] if contains else None)
                if chosen:
                    candidate_dir = os.path.join(".", chosen)
                    candidate_fileid = chosen
            except Exception:
                pass

        # If no name-only match , return the no-matches-found response
        if not candidate_dir:
            return JSONResponse(
                content={"message": "Please provide original lease first. Original abstraction unavailable."},
                status_code=HTTPStatus.NOT_FOUND.value,
            )

        # step 3: if directory somehow missing, return specified response
        if not os.path.isdir(candidate_dir):
            return JSONResponse(
                content={"message": "Please provide original lease first. Original abstraction unavailable."},
                status_code=HTTPStatus.NOT_FOUND.value,
            )

        # Match exists: load latest original lease JSON (original_lease.json or original_lease_<x>.json)
        pattern = re.compile(r"^(?:original|orignal)_lease(?:_(\d+))?\.json$", re.IGNORECASE)
        versions = []
        try:
            for name in os.listdir(candidate_dir):
                match = pattern.match(name)
                if match:
                    version = int(match.group(1)) if match.group(1) else 0
                    versions.append((version, name))
        except Exception:
            versions = []

        if not versions:
            return JSONResponse(
                content={
                    "message": "Original abstraction files not found in matched directory.",
                    "fileid": candidate_fileid,
                },
                status_code=HTTPStatus.NOT_FOUND.value,
            )

        versions.sort(key=lambda x: x[0])
        latest_version, latest_file = versions[-1]
        latest_path = os.path.join(candidate_dir, latest_file)

        input_json = None
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            try:
                input_json = json.loads(raw_text)
            except Exception:
                input_json = raw_text
        except Exception:
            input_json = None
        # Read amendment file and create base64 for the payload
        data = await amendment.read()
        base64_string = base64.b64encode(data).decode("utf-8")
        amendment_filename = amendment.filename or "amendment.pdf"

        # Load schema for amendment analysis as JSON_STRUCTURE
        with open("./utils/references/lease_abstraction.json") as file:
            original_lease_data_template = json.load(file)

        payload = [
            {"role": "system", "content": AMENDMENT_ANALYSIS['system'].format(INPUT_JSON = json.dumps(input_json), JSON_STRUCTURE = json.dumps(original_lease_data_template), DOCUMENT_NAME = amendment_filename)},
            {
                "role": "user", "content": 
                [
                    {
                        "type": "input_file", 
                        "filename": amendment_filename,
                        "file_data": f"data:application/pdf;base64,{base64_string}"
                    },
                    {
                        "type": "input_text", 
                        "text": AMENDMENT_ANALYSIS['user']
                    }
                ]
            }
        ]
        
        print(payload[0]['content'])
        print('i got here')
        print('streaming start')
        response = llm_adapter.get_non_streaming_response(payload)
        full_text_response = response.output_text
        # for event in response:
        #     if event.type == "response.output_text.delta":
        #         full_text_response+= event.delta
        #         print(event.delta, end="", flush=True)
        #     elif event.type == "response.completed":
        #         print()  # finish with a newline        # Store the response as the next version: original_lease_<x>.json
        try:
            next_version = (max(v for v, _ in versions) + 1) if versions else 0
            new_output_path = os.path.join(candidate_dir, f"original_lease_{next_version}.json")
            result_text = full_text_response 
            
            try:
                parsed_json = json.loads(result_text)
                with open(new_output_path, "w", encoding="utf-8") as out_file:
                    json.dump(parsed_json, out_file, ensure_ascii=False, indent=2)
                return parsed_json

            except json.JSONDecodeError:
                # Try to recover by extracting content between first { and last }
                first_open = result_text.find('{')
                last_close = result_text.rfind('}')
                json_substring = result_text[first_open:last_close]
                parsed_json = json.loads(json_substring)
                # if first_open != -1 and last_close != -1 and first_open < last_close:
                #     json_substring = result_text[first_open:last_close + 1]
                #     print('json substring here --->>> ')
                #     print(json_substring)
                #     try:
                #         parsed_json = json.loads(json_substring)
                #         with open(new_output_path, "w", encoding="utf-8") as out_file:
                #             json.dump(parsed_json, out_file, ensure_ascii=False, indent=2)
                #         return parsed_json
                #     except json.JSONDecodeError:
                #         print("Failed to parse even after trimming to JSON substring.")
                # else:
                #     print("Could not find valid JSON boundaries.")
                # with open(new_output_path, "w", encoding="utf-8") as out_file:
                #     out_file.write(result_text)
        except Exception as write_error:
            logger.error(write_error)

        # Return the model output directly, consistent with get_lease_abstraction
        return {}
    except Exception as error:
        logger.error(error)
        return JSONResponse(
            content={
                "message": "Something went wrong, please contact support@stealth.com"
            },
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value,
        )