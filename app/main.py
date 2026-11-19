from __future__ import annotations

import asyncio
import re
from typing import Literal

import bleach
import httpx
from bleach.css_sanitizer import CSSSanitizer
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

app = FastAPI(title="HandToDigital", version="1.1.0")

# EC2 metadata is cached for the lifetime of this process. IMDSv2 is mandatory.
_instance_info: dict | None = None


@app.middleware("http")
async def prevent_api_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


async def get_instance_info() -> dict:
    """Read non-sensitive EC2 identity fields through IMDSv2; safe outside EC2."""
    global _instance_info
    if _instance_info is not None:
        return _instance_info

    metadata_url = "http://169.254.169.254/latest"
    timeout = httpx.Timeout(1.5, connect=0.8)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            token_response = await client.put(
                f"{metadata_url}/api/token",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            )
            token_response.raise_for_status()
            token = token_response.text
            headers = {"X-aws-ec2-metadata-token": token}

            async def read(path: str) -> str:
                response = await client.get(f"{metadata_url}/meta-data/{path}", headers=headers)
                response.raise_for_status()
                return response.text.strip()

            instance_id, availability_zone, private_ip = await asyncio.gather(
                read("instance-id"),
                read("placement/availability-zone"),
                read("local-ipv4"),
            )
            _instance_info = {
                "available": True,
                "instance_id": instance_id,
                "availability_zone": availability_zone,
                "private_ip": private_ip,
            }
    except (httpx.HTTPError, OSError, ValueError):
        # Local development and non-EC2 environments do not expose instance metadata.
        return {"available": False, "message": "Instance metadata is unavailable."}
    return _instance_info


ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS).union({
    "html","head","body","title","meta","style","div","span","p","br","hr",
    "h1","h2","h3","h4","strong","b","em","i","u","s","ul","ol","li",
    "table","thead","tbody","tr","th","td","blockquote","pre","code",
    "section","article","header","footer","sup","sub"
})
ALLOWED_ATTRIBUTES = {"*":["class","style","dir","lang","title","align"]}
CSS = CSSSanitizer(allowed_css_properties={
    "color","background","background-color","font-family","font-size","font-weight",
    "font-style","line-height","text-align","direction","margin","margin-top",
    "margin-right","margin-bottom","margin-left","padding","border","border-top",
    "border-bottom","border-left","border-right","border-color","border-width",
    "border-style","border-collapse","width","height","max-width","min-height",
    "display","vertical-align","white-space","list-style-type","letter-spacing",
    "word-spacing","text-decoration","box-sizing","gap","position","overflow"
})


class PageRequest(BaseModel):
    provider: Literal["gemini","openai"] = "gemini"
    api_key: SecretStr
    model: str = Field(min_length=1,max_length=120)
    image_data_url: str = Field(min_length=30,max_length=18_000_000)
    page_number: int = Field(ge=1)
    language: Literal["auto","ar","en","mixed"] = "auto"
    output_style: Literal["typed","handwritten"] = "typed"
    paper_style: Literal["lined","grid","plain","college"] = "lined"
    extra_instructions: str = Field(default="",max_length=2000)


NOTE_PROMPT = """You are an expert knowledge extraction specialist, technical editor, and educational content creator.

Your task is to transform an uploaded Arabic handwritten notebook page into accurate, structured English educational content.

PRIMARY OBJECTIVE
Extract ALL information and explanations from the handwritten notes. This is a faithful reconstruction and reorganization, NOT a summary.
- DO NOT omit any information.
- DO NOT summarize or shorten any handwritten explanations.
- Preserve 100% of the original knowledge, descriptions, and notes.

CONTENT EXTRACTION
Read the entire handwritten page carefully. Extract every available piece of information, including:
- Main titles, Chapter names, Section headings
- Definitions, Explanations, Concepts
- Properties, Characteristics, Rules, Steps, Procedures
- Lists, Tables, Comparisons, Examples, Applications
- Advantages, Disadvantages, Notes, Warnings, Important points
- Formulas, Equations, Code snippets, Diagrams and relationships

TRANSLATION RULES
Translate all Arabic content into English. The output must contain English only. Use professional academic English. Correct grammar and spelling. Preserve the original meaning exactly.

INFORMATION ORGANIZATION & RESTRUCTURING
The original notes may contain scattered thoughts. Restructure them into a highly logical, hierarchical programming documentation format.
- Group related concepts together.
- Use clear hierarchical headings (I, II, III, etc.).
- You may change the order to improve logical flow, but MUST NOT delete, summarize, or reduce any original handwritten explanation.

EXAMPLES & CODE GENERATION
The original handwritten notes DO NOT contain code examples. Whenever a programming concept, rule, or architecture pattern is explained, generate a clear, modern, well-commented C# code example.
- Follow C# best practices.
- Add brief comments explaining how the code relates to the notes.
- Clearly label each section as Code Example:.

TABLES, DIAGRAMS & UNCLEAR TEXT
Convert visual relationships into clear textual descriptions. If a word cannot be read, write: [Handwriting unclear].

OUTPUT REQUIREMENTS
Output ONLY structured text in English. Do not generate HTML or CSS. Use readable headings and lists. Use fenced code blocks only for C# examples.
Additional user instructions: {extra_instructions}
"""

NOTEBOOK_CSS = """
@import url("https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500&display=swap");
* { box-sizing: border-box; }
body { margin: 0; padding: 0; background-color: #f0f0f0; font-family: "Fira Code", monospace; }
.page {
  width: 100%; max-width: 1200px; margin: 0 auto; min-height: 100vh;
  background-color: #fff;
  background-image: linear-gradient(to right, #ffcccc 2px, transparent 2px, transparent 10px, #ffcccc 12px, transparent 12px), linear-gradient(#e0e0ff 1px, transparent 1px);
  background-size: 100% 100%, 100% 30px; background-position: 50px 0, 0 0;
  padding: 40px 40px 40px 80px; position: relative; color: #333; line-height: 1.6;
}
.spiral {
  position: absolute; left: 15px; top: 0; bottom: 0; width: 30px;
  background-image: radial-gradient(circle at center, #ccc 5px, #999 6px, #999 7.5px, transparent 8px);
  background-size: 100% 30px; background-repeat: repeat-y; background-position: center 15px;
}
h1 { color: #2e7d32; text-decoration: underline; margin-top: 0; }
h2 { color: #1565c0; margin-top: 30px; }
h3 { color: #0d47a1; margin-top: 20px; }
code { background: #eef; border: 1px solid #bbdefb; padding: 2px 4px; border-radius: 3px; }
.code-box { background: #f8fbff; border: 1px solid #bbdefb; padding: 15px; margin: 15px 0; border-radius: 5px; break-inside: avoid; font-size: 0.9em; white-space: pre-wrap; overflow-wrap: anywhere; }
.note-box { background: #fff9c4; border: 1px solid #fbc02d; padding: 15px; margin: 15px 0; border-radius: 5px; break-inside: avoid; }
.highlight { background-color: #d4f5d4; padding: 2px 5px; border-radius: 4px; }
ul, ol { margin-bottom: 20px; }
li { margin-bottom: 5px; }
.content { position: relative; z-index: 1; }
p { margin: 0 0 12px; white-space: pre-wrap; }
"""

def prompt_for(req: PageRequest) -> str:
    return NOTE_PROMPT.format(extra_instructions=req.extra_instructions.strip() or "None")


def text_to_html(text: str) -> str:
    """Render structured model text safely inside the fixed notebook template."""
    import html
    fence = chr(96) * 3
    parts: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    in_code = False
    list_tag: str | None = None

    def flush_paragraph():
        if paragraph:
            parts.append("<p>" + "<br>".join(html.escape(x) for x in paragraph) + "</p>")
            paragraph.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            parts.append("</" + list_tag + ">")
            list_tag = None

    for line in text.replace("\r", "").split("\n"):
        s = line.strip()
        if s.startswith(fence):
            flush_paragraph()
            close_list()
            if in_code:
                parts.append('<pre class="code-box"><code>' + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not s:
            flush_paragraph()
            close_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", s)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            parts.append("<h" + str(level) + ">" + html.escape(heading.group(2)) + "</h" + str(level) + ">")
            continue
        bullet = re.match(r"^(?:[-*•])\s+(.+)$", s)
        numbered = re.match(r"^\d+[.)]\s+(.+)$", s)
        if bullet or numbered:
            flush_paragraph()
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                close_list()
                parts.append("<" + tag + ">")
                list_tag = tag
            value = (bullet or numbered).group(1)
            parts.append("<li>" + html.escape(value) + "</li>")
            continue
        close_list()
        paragraph.append(s)
    flush_paragraph()
    close_list()
    if in_code:
        parts.append('<pre class="code-box"><code>' + html.escape("\n".join(code_lines)) + "</code></pre>")
    return ("<!doctype html><html><head><meta charset='utf-8'><style>" + NOTEBOOK_CSS +
            "</style></head><body><main class='page'><div class='spiral'></div>" +
            "<article class='content'>" + "".join(parts) + "</article></main></body></html>")


async def gemini(req: PageRequest, prompt: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", req.model):
        raise HTTPException(status_code=400, detail="اسم النموذج غير صالح.")
    parts = req.image_data_url.split(",",1)
    if len(parts)!=2: raise HTTPException(status_code=400,detail="صورة الصفحة غير صالحة.")
    mime = "image/jpeg" if "image/jpeg" in parts[0].lower() else "image/png"
    url="https://generativelanguage.googleapis.com/v1beta/interactions"
    async with httpx.AsyncClient(timeout=180) as client:
        res=await client.post(url,headers={"x-goog-api-key":req.api_key.get_secret_value()},json={
            "model":req.model,
            "system_instruction":prompt,
            "input":[{
                "type":"user_input",
                "content":[
                    {"type":"image","mime_type":mime,"data":parts[1]},
                    {"type":"text","text":"Transcribe and reconstruct this page according to the system instructions. Return only the complete HTML document."}
                ]
            }],
            "store":False
        })
    try:
        payload = res.json()
    except ValueError:
        payload = {}

    if res.is_error:
        error = payload.get("error") or {}
        msg = error.get("message") if isinstance(error, dict) else str(error)
        raise HTTPException(status_code=502, detail=(msg or "Gemini API request failed.")[:600])

    if payload.get("status") in {"failed", "incomplete", "cancelled"}:
        errors = payload.get("errors") or []
        msg = next((e.get("message") for e in errors if isinstance(e, dict) and e.get("message")), None)
        raise HTTPException(status_code=502, detail=msg or f"Gemini interaction status: {payload.get('status')}")

    output = []
    for step in payload.get("steps", []):
        if isinstance(step, dict) and step.get("type") == "model_output":
            output.extend(
                item.get("text", "") for item in step.get("content", [])
                if isinstance(item, dict) and item.get("type") == "text"
            )
    result = "".join(output).strip()
    if not result:
        errors = payload.get("errors") or []
        msg = next((e.get("message") for e in errors if isinstance(e, dict) and e.get("message")), None)
        raise HTTPException(status_code=502, detail=msg or "استجابة Gemini فارغة أو غير مفهومة.")
    return result


async def openai(req: PageRequest, prompt: str) -> str:
    async with httpx.AsyncClient(timeout=180) as client:
        res=await client.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization":"Bearer "+req.api_key.get_secret_value()},
            json={"model":req.model,"temperature":0.1,"max_tokens":8192,"messages":[{"role":"user","content":[
                {"type":"text","text":prompt},{"type":"image_url","image_url":{"url":req.image_data_url,"detail":"high"}}]}]})
    if res.is_error:
        try: msg=res.json().get("error",{}).get("message","OpenAI API request failed.")
        except Exception: msg="OpenAI API request failed."
        raise HTTPException(status_code=502,detail=msg[:600])
    try: return res.json()["choices"][0]["message"]["content"]
    except (KeyError,IndexError,TypeError): raise HTTPException(status_code=502,detail="استجابة OpenAI فارغة أو غير مفهومة.")


@app.get("/api/health")
async def health():
    return {"status":"ok","service":"HandToDigital"}


@app.get("/api/instance-info")
async def instance_info():
    return await get_instance_info()


@app.post("/api/convert-page")
async def convert_page(req: PageRequest):
    if not req.image_data_url.startswith("data:image/"):
        raise HTTPException(status_code=400,detail="يجب إرسال صورة صفحة.")
    try:
        raw=await (gemini(req,prompt_for(req)) if req.provider=="gemini" else openai(req,prompt_for(req)))
        return {"page_number":req.page_number,"html":text_to_html(raw),"instance_info":await get_instance_info()}
    except httpx.TimeoutException: raise HTTPException(status_code=504,detail="انتهت مهلة الاتصال بمزود الذكاء الاصطناعي.")
    except httpx.HTTPError: raise HTTPException(status_code=502,detail="تعذر الاتصال بمزود الذكاء الاصطناعي.")


app.mount("/",StaticFiles(directory="static",html=True),name="static")
