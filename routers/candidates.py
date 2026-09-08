import json
import os
import re
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PyPDF2 import PdfReader

from core.auth import get_current_user
from core.aws_clients import s3, bedrock_agent
from core.config import (
    S3_BUCKET,
    S3_PREFIX,
    KNOWLEDGE_BASE_ID,
    DATA_SOURCE_ID,
    MAX_CV_SIZE_BYTES,
)
from core.helpers import (
    get_candidate_record,
    save_candidate_record,
    build_sources,
)
from core.llm import retrieve_candidate, generate_answer, evaluate_candidate
from core.models import (
    AskCandidateRequest,
    AskCandidateResponse,
    CandidateEvaluation,
    EvaluateCandidateRequest,
    EvaluateJobRequest,
)

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


# ============================================================
# HELPERS
# ============================================================


def _clean_extracted_text(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-|\u2022")
    return value or None


def extract_candidate_profile_from_pdf(pdf_bytes: bytes) -> dict:
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    lines = [_clean_extracted_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    email = re.search(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.I
    )
    phone = re.search(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", text)
    name = None
    for line in lines[:12]:
        words = line.split()
        if 2 <= len(words) <= 5 and (
            not email or email.group(0).lower() not in line.lower()
        ):
            if all(
                re.match(r"^[^\W\d_][\w''-]*$", word, re.UNICODE)
                for word in words
            ):
                name = line
                break
    location = None
    title = None
    for line in lines[:40]:
        lower = line.lower()
        if ":" in line and any(
            x in lower
            for x in ("ubicaci\u00f3n", "location", "ciudad", "direcci\u00f3n")
        ):
            location = _clean_extracted_text(line.split(":", 1)[1])
        if ":" in line and any(
            x in lower
            for x in ("perfil", "professional title", "cargo", "title")
        ):
            title = _clean_extracted_text(line.split(":", 1)[1])
    if not title:
        title = next(
            (
                line
                for line in lines[:20]
                if any(
                    x in line.lower()
                    for x in (
                        "developer",
                        "engineer",
                        "manager",
                        "designer",
                        "analyst",
                        "desarrollador",
                        "ingeniero",
                        "gerente",
                    )
                )
            ),
            None,
        )
    return {
        "name": _clean_extracted_text(name),
        "email": _clean_extracted_text(email.group(0) if email else None),
        "phone": _clean_extracted_text(phone.group(0) if phone else None),
        "location": location,
        "professional_title": _clean_extracted_text(title),
    }


def _fallback_candidate_name(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    return _clean_extracted_text(re.sub(r"[_-]+", " ", stem)) or "Candidato"


def _service_error_message(error: Exception) -> str:
    response = getattr(error, "response", {})
    aws_error = response.get("Error", {}) if isinstance(response, dict) else {}
    return aws_error.get(
        "Message", "No fue posible completar el registro del candidato."
    )


async def _prepare_bulk_candidate(
    file: UploadFile,
    current_user: dict,
    start_ingestion: bool = True,
) -> dict:
    original_filename = os.path.basename(file.filename or "")
    if not original_filename.lower().endswith(".pdf"):
        raise ValueError("El CV debe estar en formato PDF.")
    content = await file.read()
    if not content:
        raise ValueError("El archivo est\u00e1 vac\u00edo.")
    if len(content) > MAX_CV_SIZE_BYTES:
        raise ValueError("El archivo supera el l\u00edmite de 15 MB.")
    if not content.startswith(b"%PDF"):
        raise ValueError("El archivo no tiene una firma PDF v\u00e1lida.")
    try:
        profile = extract_candidate_profile_from_pdf(content)
    except Exception as error:
        raise ValueError("No fue posible procesar el PDF.") from error
    candidate_id = str(uuid.uuid4())
    name = profile["name"] or _fallback_candidate_name(original_filename)
    filename = f"cv-{candidate_id}.pdf"
    metadata_filename = f"{filename}.metadata.json"
    s3_key = f"{S3_PREFIX}/{filename}"
    metadata_key = f"{S3_PREFIX}/{metadata_filename}"
    metadata = {
        "metadataAttributes": {
            "candidate_id": {
                "value": {"type": "STRING", "stringValue": candidate_id}
            },
            "candidate_name": {
                "value": {"type": "STRING", "stringValue": name}
            },
            "user_sub": {
                "value": {
                    "type": "STRING",
                    "stringValue": current_user["sub"],
                }
            },
        }
    }
    try:
        s3.put_object(
            Bucket=S3_BUCKET, Key=s3_key, Body=content, ContentType="application/pdf"
        )
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=metadata_key,
            Body=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        ingestion = {}
        if start_ingestion:
            ingestion = bedrock_agent.start_ingestion_job(
                knowledgeBaseId=KNOWLEDGE_BASE_ID, dataSourceId=DATA_SOURCE_ID
            ).get("ingestionJob", {})
        record = {
            "candidate_id": candidate_id,
            "owner_id": current_user["sub"],
            "user_sub": current_user["sub"],
            "name": name,
            **profile,
            "filename": filename,
            "original_filename": original_filename,
            "s3_location": f"s3://{S3_BUCKET}/{s3_key}",
            "metadata_location": f"s3://{S3_BUCKET}/{metadata_key}",
            "ingestion_job_id": ingestion.get("ingestionJobId"),
            "ingestion_status": ingestion.get("status") or "PENDING",
            "indexed": False,
        }
        save_candidate_record(record)
        return record
    except Exception as error:
        try:
            s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
            s3.delete_object(Bucket=S3_BUCKET, Key=metadata_key)
        except Exception:
            pass
        raise RuntimeError(_service_error_message(error)) from error


# ============================================================
# ENDPOINTS
# ============================================================


@router.post("/bulk")
async def create_candidates_bulk(
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    if not files:
        raise HTTPException(
            status_code=400, detail="Debes seleccionar al menos un PDF."
        )
    if len(files) > 100:
        raise HTTPException(
            status_code=400, detail="Puedes subir un m\u00e1ximo de 100 PDFs por lote."
        )
    candidates, errors = [], []
    for file in files:
        original_filename = os.path.basename(file.filename or "")
        try:
            candidates.append(
                await _prepare_bulk_candidate(
                    file, current_user, start_ingestion=False
                )
            )
        except (ValueError, RuntimeError) as error:
            errors.append(
                {"original_filename": original_filename, "error": str(error)}
            )
        except Exception:
            errors.append(
                {
                    "original_filename": original_filename,
                    "error": "Error inesperado al procesar el archivo.",
                }
            )
    ingestion_error = None
    if candidates:
        try:
            ingestion = bedrock_agent.start_ingestion_job(
                knowledgeBaseId=KNOWLEDGE_BASE_ID,
                dataSourceId=DATA_SOURCE_ID,
            ).get("ingestionJob", {})
            ingestion_job_id = ingestion.get("ingestionJobId")
            ingestion_status = ingestion.get("status") or "STARTING"
            for candidate in candidates:
                candidate["ingestion_job_id"] = ingestion_job_id
                candidate["ingestion_status"] = ingestion_status
                save_candidate_record(candidate)
        except Exception as error:
            ingestion_error = _service_error_message(error)
            for candidate in candidates:
                candidate["ingestion_status"] = "ERROR"
                candidate["ingestion_error"] = ingestion_error
                save_candidate_record(candidate)
    result = {
        "processed": len(files),
        "successful": len(candidates),
        "failed": len(errors),
        "total": len(files),
        "created": len(candidates),
        "candidates": candidates,
        "errors": errors,
    }
    if ingestion_error:
        result["ingestion_error"] = ingestion_error
    return result


@router.post("")
async def create_candidate(
    name: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    if not name.strip():
        raise HTTPException(
            status_code=400,
            detail="El nombre del candidato es obligatorio.",
        )
    if not file.filename:
        raise HTTPException(
            status_code=400, detail="Debes enviar un archivo."
        )
    extension = os.path.splitext(file.filename)[1].lower()
    if extension != ".pdf":
        raise HTTPException(
            status_code=400, detail="El CV debe estar en formato PDF."
        )
    candidate_id = str(uuid.uuid4())
    filename = f"cv-{candidate_id}.pdf"
    metadata_filename = f"cv-{candidate_id}.pdf.metadata.json"
    s3_key = f"{S3_PREFIX}/{filename}"
    metadata_key = f"{S3_PREFIX}/{metadata_filename}"
    try:
        file_content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"No se pudo leer el PDF: {str(e)}"
        )
    if not file_content:
        raise HTTPException(
            status_code=400, detail="El archivo est\u00e1 vac\u00edo."
        )
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=file_content,
            ContentType="application/pdf",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error subiendo CV a S3: {str(e)}"
        )
    metadata = {
        "metadataAttributes": {
            "candidate_id": {
                "value": {"type": "STRING", "stringValue": candidate_id}
            },
            "candidate_name": {
                "value": {"type": "STRING", "stringValue": name.strip()}
            },
        }
    }
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=metadata_key,
            Body=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as e:
        try:
            s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Error creando metadata del candidato: {str(e)}",
        )
    try:
        ingestion_response = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID, dataSourceId=DATA_SOURCE_ID
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "CV subido correctamente, pero no se pudo "
                f"iniciar la ingestion de Bedrock: {str(e)}"
            ),
        )
    ingestion_job = ingestion_response.get("ingestionJob", {})
    ingestion_job_id = ingestion_job.get("ingestionJobId")
    ingestion_status = ingestion_job.get("status")
    candidate_record = {
        "candidate_id": candidate_id,
        "owner_id": current_user["sub"],
        "user_sub": current_user["sub"],
        "name": name.strip(),
        "filename": filename,
        "s3_location": f"s3://{S3_BUCKET}/{s3_key}",
        "metadata_location": f"s3://{S3_BUCKET}/{metadata_key}",
        "ingestion_job_id": ingestion_job_id,
        "ingestion_status": ingestion_status,
        "indexed": False,
    }
    try:
        save_candidate_record(candidate_record)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "El CV fue subido e ingestion iniciada, "
                f"pero no se pudo guardar el candidato en DynamoDB: {str(e)}"
            ),
        )
    return {
        "message": "CV uploaded successfully",
        "candidate": {"id": candidate_id, "name": name.strip()},
        "file": filename,
        "metadata_file": metadata_filename,
        "s3_location": f"s3://{S3_BUCKET}/{s3_key}",
        "metadata_location": f"s3://{S3_BUCKET}/{metadata_key}",
        "knowledge_base_id": KNOWLEDGE_BASE_ID,
        "data_source_id": DATA_SOURCE_ID,
        "ingestion_job_id": ingestion_job_id,
        "ingestion_status": ingestion_status,
    }


@router.get("")
def list_candidates(current_user: dict = Depends(get_current_user)):
    try:
        from core.aws_clients import candidates_table

        response = candidates_table.scan()
        candidates = response.get("Items", [])
        owner_id = current_user["sub"]
        user_candidates = [
            c for c in candidates if c.get("owner_id") == owner_id
        ]
        return {"candidates": user_candidates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{candidate_id}")
def get_candidate(
    candidate_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        candidate = get_candidate_record(candidate_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a este candidato.",
            )
        ingestion_job_id = candidate.get("ingestion_job_id")
        ingestion_status = candidate.get("ingestion_status")
        indexed = candidate.get("indexed", False)
        if ingestion_job_id:
            try:
                response = bedrock_agent.get_ingestion_job(
                    knowledgeBaseId=KNOWLEDGE_BASE_ID,
                    dataSourceId=DATA_SOURCE_ID,
                    ingestionJobId=ingestion_job_id,
                )
                job = response.get("ingestionJob", {})
                ingestion_status = job.get("status", ingestion_status)
                indexed = ingestion_status == "COMPLETE"
                candidate["ingestion_status"] = ingestion_status
                candidate["indexed"] = indexed
                save_candidate_record(candidate)
            except Exception as ingestion_error:
                print(
                    "WARNING GET CANDIDATE INGESTION STATUS:",
                    str(ingestion_error),
                )
        return {
            "candidate_id": candidate.get("candidate_id"),
            "name": candidate.get("name"),
            "filename": candidate.get("filename"),
            "s3_location": candidate.get("s3_location"),
            "metadata_location": candidate.get("metadata_location"),
            "ingestion_job_id": ingestion_job_id,
            "ingestion_status": ingestion_status,
            "indexed": indexed,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{candidate_id}/download")
def download_candidate_cv(
    candidate_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        candidate = get_candidate_record(candidate_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a este CV.",
            )
        s3_location = candidate.get("s3_location")
        if not s3_location:
            raise HTTPException(
                status_code=404,
                detail="El CV no tiene ubicaci\u00f3n en S3.",
            )
        prefix = f"s3://{S3_BUCKET}/"
        if s3_location.startswith(prefix):
            s3_key = s3_location[len(prefix) :]
        else:
            s3_key = s3_location
        download_filename = candidate.get("filename")
        if candidate.get("name"):
            clean_name = candidate["name"].strip().replace(" ", "_")
            download_filename = f"{clean_name}_CV.pdf"
        if not download_filename:
            download_filename = "CV.pdf"
        download_url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": s3_key,
                "ResponseContentType": "application/pdf",
                "ResponseContentDisposition": (
                    f'attachment; filename="{download_filename}"'
                ),
            },
            ExpiresIn=300,
        )
        return {"download_url": download_url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="No fue posible generar la descarga del CV.",
        )


@router.delete("")
def delete_all_candidates(
    current_user: dict = Depends(get_current_user),
):
    try:
        from core.aws_clients import candidates_table, evaluations_table

        owner_id = current_user["sub"]
        scan_kwargs = {}
        owned_candidates = []
        while True:
            page = candidates_table.scan(**scan_kwargs)
            owned_candidates.extend(
                c
                for c in page.get("Items", [])
                if c.get("owner_id") == owner_id
            )
            last_key = page.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
        deleted = 0
        errors = []
        for candidate in owned_candidates:
            candidate_id = candidate.get("candidate_id")
            try:
                from boto3.dynamodb.conditions import Key

                evaluations = evaluations_table.query(
                    IndexName="candidate-index",
                    KeyConditionExpression=Key("candidate_id").eq(
                        candidate_id
                    ),
                )
                for evaluation in evaluations.get("Items", []):
                    evaluations_table.delete_item(
                        Key={
                            "job_id": evaluation["job_id"],
                            "candidate_id": evaluation["candidate_id"],
                        }
                    )
                candidates_table.delete_item(
                    Key={"candidate_id": candidate_id}
                )
                for location_key in ("s3_location", "metadata_location"):
                    location = candidate.get(location_key)
                    if location:
                        parts = location.split("/", 3)
                        if len(parts) == 4:
                            s3.delete_object(Bucket=parts[2], Key=parts[3])
                deleted += 1
            except Exception as error:
                errors.append(
                    {"candidate_id": candidate_id, "error": str(error)}
                )
        return {
            "requested": len(owned_candidates),
            "deleted": deleted,
            "failed": len(errors),
            "errors": errors,
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="No fue posible eliminar los candidatos.",
        )


@router.delete("/{candidate_id}")
def delete_candidate(
    candidate_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        from boto3.dynamodb.conditions import Key
        from core.aws_clients import candidates_table, evaluations_table

        candidate = get_candidate_record(candidate_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso sobre este candidato.",
            )
        evaluations = evaluations_table.query(
            IndexName="candidate-index",
            KeyConditionExpression=Key("candidate_id").eq(candidate_id),
        )
        for evaluation in evaluations.get("Items", []):
            evaluations_table.delete_item(
                Key={
                    "job_id": evaluation["job_id"],
                    "candidate_id": evaluation["candidate_id"],
                }
            )
        candidates_table.delete_item(Key={"candidate_id": candidate_id})
        if candidate.get("s3_location"):
            bucket = candidate["s3_location"].split("/")[2]
            key = "/".join(candidate["s3_location"].split("/")[3:])
            s3.delete_object(Bucket=bucket, Key=key)
        return {
            "message": "Candidato eliminado correctamente.",
            "candidate_id": candidate_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{candidate_id}/ingestion/{ingestion_job_id}")
def get_ingestion_status(
    candidate_id: str,
    ingestion_job_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        response = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            dataSourceId=DATA_SOURCE_ID,
            ingestionJobId=ingestion_job_id,
        )
        job = response.get("ingestionJob", {})
        status = job.get("status")
        indexed = status == "COMPLETE"
        candidate = get_candidate_record(candidate_id)
        if candidate:
            candidate["ingestion_status"] = status
            candidate["indexed"] = indexed
            save_candidate_record(candidate)
        return {
            "candidate_id": candidate_id,
            "ingestion_job_id": ingestion_job_id,
            "status": status,
            "indexed": indexed,
            "statistics": job.get("statistics"),
            "failure_reasons": job.get("failureReasons", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{candidate_id}/ask", response_model=AskCandidateResponse)
def ask_candidate(
    candidate_id: str,
    request: AskCandidateRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        candidate = get_candidate_record(candidate_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para consultar este candidato.",
            )
        results = retrieve_candidate(
            candidate_id=candidate_id, question=request.question
        )
        if not results:
            return AskCandidateResponse(
                candidate_id=candidate_id,
                answer=(
                    "No encontr\u00e9 informaci\u00f3n relevante "
                    "sobre este candidato en su CV."
                ),
                sources=[],
            )
        answer = generate_answer(
            candidate_id=candidate_id,
            question=request.question,
            results=results,
        )
        sources = build_sources(results)
        return AskCandidateResponse(
            candidate_id=candidate_id, answer=answer, sources=sources
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{candidate_id}/evaluate", response_model=CandidateEvaluation
)
def evaluate_candidate_endpoint(
    candidate_id: str,
    request: EvaluateCandidateRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        candidate = get_candidate_record(candidate_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para evaluar este candidato.",
            )
        results = retrieve_candidate(
            candidate_id=candidate_id, question=request.job_description
        )
        evaluation = evaluate_candidate(
            candidate_id=candidate_id,
            job_description=request.job_description,
            results=results,
        )
        sources = build_sources(results)
        return CandidateEvaluation(
            candidate_id=candidate_id,
            match_score=evaluation.get("match_score", 0),
            recommendation=evaluation.get("recommendation", "LOW_MATCH"),
            requirements=evaluation.get("requirements", []),
            strengths=evaluation.get("strengths", []),
            gaps=evaluation.get("gaps", []),
            summary=evaluation.get("summary", ""),
            sources=sources,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{candidate_id}/evaluate-job", response_model=CandidateEvaluation
)
def evaluate_candidate_job(
    candidate_id: str,
    request: EvaluateJobRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        from core.llm import evaluate_and_save

        result = evaluate_and_save(
            candidate_id=candidate_id,
            job_id=request.job_id,
            current_user=current_user,
        )
        return CandidateEvaluation(**result)
    except ValueError as e:
        detail = str(e)
        status = 404 if "no encontrado" in detail.lower() or "no encontrada" in detail.lower() else 403
        raise HTTPException(status_code=status, detail=detail)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{candidate_id}/evaluations")
def get_candidate_evaluations(
    candidate_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        from core.aws_clients import evaluations_table
        from core.helpers import parse_json_field
        from boto3.dynamodb.conditions import Key

        candidate = get_candidate_record(candidate_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="Candidato no encontrado."
            )
        if candidate.get("owner_id") != current_user["sub"]:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso sobre este candidato.",
            )
        response = evaluations_table.query(
            IndexName="candidate-index",
            KeyConditionExpression=Key("candidate_id").eq(candidate_id),
        )
        evaluations = response.get("Items", [])
        for item in evaluations:
            item["requirements"] = parse_json_field(
                item.get("requirements", [])
            )
            item["strengths"] = parse_json_field(item.get("strengths", []))
            item["gaps"] = parse_json_field(item.get("gaps", []))
        return {
            "candidate_id": candidate_id,
            "candidate_name": candidate.get("name", ""),
            "total": len(evaluations),
            "evaluations": evaluations,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
