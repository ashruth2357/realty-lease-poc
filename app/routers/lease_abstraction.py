import base64
import asyncio
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
from utils.prompts import (
    GENERATE_AMENDMENT_EXECUTIVE_SUMMARY,
    GENERATE_AMENDMENT_LEASE_INFORMATION,
    GENERATE_AMENDMENT_SPACE,
    GENERATE_AMENDMENT_CHARGE_SCHEDULES,
    GENERATE_AMENDMENT_OTHER_LEASE_PROVISIONS,
)
from utils.prompts import (
    GENERATE_EXECUTIVE_SUMMARY,
    GENERATE_LEASE_INFORMATION,
    GENERATE_SPACE,
    GENERATE_CHARGE_SCHEDULES,
    GENERATE_OTHER_LEASE_PROVISIONS,
)
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
        
        # Read file bytes once
        file_bytes = await assets.read()

        chunker = PDFChunker(overlap_percentage=0.2)
        
        # Process the PDF from bytes
        chunks = chunker.process_pdf(file_bytes, extract_tables=True)
        
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
        
        # Prepare base64 and filename for payload and load schema
        base64_string = base64.b64encode(file_bytes).decode("utf-8")
        original_filename = assets.filename or "uploaded_file.pdf"
        with open("./utils/references/lease_abstraction.json", "r", encoding="utf-8") as file:
            schema_template = json.load(file)

        # Helper to run a scoped prompt and return parsed JSON
        def run_scoped_prompt(prompt_dict):
            payload = [
                {
                    "role": "system",
                    "content": prompt_dict["system"].format(JSON_STRUCTURE=json.dumps(schema_template)),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": original_filename,
                            "file_data": f"data:application/pdf;base64,{base64_string}",
                        },
                        {
                            "type": "input_text",
                            "text": prompt_dict["user"],
                        },
                    ],
                },
            ]

            response = llm_adapter.get_non_streaming_response(payload)
            result_text = response.output_text
            try:
                return json.loads(result_text)
            except json.JSONDecodeError:
                # Fallback: trim to JSON boundaries
                first_open = result_text.find('{')
                last_close = result_text.rfind('}')
                if first_open != -1 and last_close != -1 and first_open < last_close:
                    trimmed = result_text[first_open:last_close + 1]
                    return json.loads(trimmed)
                raise

        # Run the five scoped prompts in parallel and merge section-wise
        scoped_prompts = [
            ("executiveSummary", GENERATE_EXECUTIVE_SUMMARY),
            ("leaseInformation", GENERATE_LEASE_INFORMATION),
            ("space", GENERATE_SPACE),
            ("chargeSchedules", GENERATE_CHARGE_SCHEDULES),
            ("otherLeaseProvisions", GENERATE_OTHER_LEASE_PROVISIONS),
        ]

        tasks = [asyncio.to_thread(run_scoped_prompt, p[1]) for p in scoped_prompts]
        results = await asyncio.gather(*tasks)

        # Merge by top-level section keys
        final_lease = {}
        section_responses = {}
        for (section_key, _), full_json in zip(scoped_prompts, results):
            if isinstance(full_json, dict):
                if section_key in full_json:
                    final_lease[section_key] = full_json.get(section_key)
                    section_responses[section_key] = full_json.get(section_key)
                else:
                    # Fallback: assign entire json if section missing
                    section_responses[section_key] = full_json
        
        # Persist outputs to a directory named after the uploaded filename
        fileid = os.path.splitext(os.path.basename(original_filename or "uploaded_file"))[0]
        output_dir = os.path.join(".", fileid)
        try:
            os.makedirs(output_dir, exist_ok=True)
            section_filename_map = {
                "executiveSummary": "original_executiveSummary.json",
                "leaseInformation": "original_leaseInformation.json",
                "space": "original_space.json",
                "chargeSchedules": "original_chargeSchedules.json",
                "otherLeaseProvisions": "original_otherLeaseProvisions.json",
            }
            for key, content in section_responses.items():
                fname = section_filename_map.get(key)
                if fname:
                    with open(os.path.join(output_dir, fname), "w", encoding="utf-8") as f:
                        json.dump(content, f, ensure_ascii=False, indent=2)
            # Save final merged output
            with open(os.path.join(output_dir, "original_lease.json"), "w", encoding="utf-8") as f:
                json.dump(final_lease, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(e)

        return {"final": final_lease, "sections": section_responses}


        
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
        file_bytes = await amendment.read()
        base64_string = base64.b64encode(file_bytes).decode("utf-8")
        amendment_filename = amendment.filename or "amendment.pdf"

        # Load schema for amendment analysis as JSON_STRUCTURE
        with open("./utils/references/lease_abstraction.json") as file:
            original_lease_data_template = json.load(file)

        # Run the five amendment-scoped prompts in parallel (single-shot) and merge by section
        def run_amendment_prompt(prompt_dict):
            payload = [
                {
                    "role": "system",
                    "content": prompt_dict["system"].format(
                        JSON_STRUCTURE=json.dumps(original_lease_data_template)
                    ),
                },
                {
                    "role": "user",
                    "content": [
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

            response = llm_adapter.get_non_streaming_response(payload)
            result_text = response.output_text
            try:
                return json.loads(result_text)
            except json.JSONDecodeError:
                first_open = result_text.find('{')
                last_close = result_text.rfind('}')
                if first_open != -1 and last_close != -1 and first_open < last_close:
                    return json.loads(result_text[first_open:last_close + 1])
                raise

        amend_scoped = [
            ("executiveSummary", GENERATE_AMENDMENT_EXECUTIVE_SUMMARY),
            ("leaseInformation", GENERATE_AMENDMENT_LEASE_INFORMATION),
            ("space", GENERATE_AMENDMENT_SPACE),
            ("chargeSchedules", GENERATE_AMENDMENT_CHARGE_SCHEDULES),
            ("otherLeaseProvisions", GENERATE_AMENDMENT_OTHER_LEASE_PROVISIONS),
        ]

        amend_tasks = [asyncio.to_thread(run_amendment_prompt, p[1]) for p in amend_scoped]
        amend_results = await asyncio.gather(*amend_tasks)

        amended_lease = {}
        amend_sections = {}
        for (section_key, _), full_json in zip(amend_scoped, amend_results):
            if isinstance(full_json, dict):
                if section_key in full_json:
                    amended_lease[section_key] = full_json.get(section_key)
                    amend_sections[section_key] = full_json.get(section_key)
                else:
                    amend_sections[section_key] = full_json
        try:
            next_version = (max(v for v, _ in versions) + 1) if versions else 0
            new_output_path = os.path.join(candidate_dir, f"original_lease_{next_version}.json")
            parsed_json = {"final": amended_lease, "sections": amend_sections}
            with open(new_output_path, "w", encoding="utf-8") as out_file:
                json.dump(parsed_json, out_file, ensure_ascii=False, indent=2)

            # Persist section-wise outputs alongside final
            try:
                section_filename_map = {
                    "executiveSummary": f"amendment_executiveSummary_{next_version}.json",
                    "leaseInformation": f"amendment_leaseInformation_{next_version}.json",
                    "space": f"amendment_space_{next_version}.json",
                    "chargeSchedules": f"amendment_chargeSchedules_{next_version}.json",
                    "otherLeaseProvisions": f"amendment_otherLeaseProvisions_{next_version}.json",
                }
                for key, content in amend_sections.items():
                    fname = section_filename_map.get(key)
                    if fname:
                        with open(os.path.join(candidate_dir, fname), "w", encoding="utf-8") as f:
                            json.dump(content, f, ensure_ascii=False, indent=2)
            except Exception as sec_err:
                logger.error(sec_err)

            return parsed_json
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