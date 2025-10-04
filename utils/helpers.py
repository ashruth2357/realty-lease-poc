import os 
import json
from pathlib import Path
from typing import Any
import fitz  # PyMuPDF
import base64
from fastapi import UploadFile

from adapters.llms._openai import _OpenAI
from adapters.llms._perplexity import _Perplexity
from adapters.llms.base import LargeLanguageModel

def get_llm_adapter() -> LargeLanguageModel:
    llm_details = json.loads(str(os.environ.get('LLM')))
    if llm_details['provider'] == "openai":
        return _OpenAI()
    else:
        return _Perplexity()
    
def save_response_to_file(response_data: str, filename: str):
    try:
        # Remove file extension from filename to use as directory name
        base_filename = Path(filename).stem
        
        # Create directory path
        directory_path = Path(f"./results/{base_filename}")
        directory_path.mkdir(parents=True, exist_ok=True)
        
        # Parse the response as JSON (assuming it's JSON format)
        try:
            response_json = json.loads(response_data)
        except json.JSONDecodeError:
            # If it's not valid JSON, wrap it in a JSON structure
            response_json = {"response": response_data}
        
        # Save to result.json
        result_file_path = directory_path / "result.json"
        with open(result_file_path, 'w', encoding='utf-8') as file:
            json.dump(response_json, file, indent=2, ensure_ascii=False)
            
        print(f"Successfully saved response to {result_file_path}")
        
    except Exception as e:
        print(f"Error saving response to file: {str(e)}")
        
def update_result_json(resultant_json, llm_iterative_response_json):
    pass
