"""
AI Skill Store MCP Server
에이전트가 AI Skill Store API를 자율적으로 사용할 수 있도록 MCP 툴을 제공합니다.

사용법:
    python mcp_server/skill_store_mcp.py

Claude Desktop 설정 예시 (claude_desktop_config.json):
{
  "mcpServers": {
    "skill-store": {
      "command": "python",
      "args": ["<path>/Skill_Store_Project/mcp_server/skill_store_mcp.py"],
      "env": {
        "SKILL_STORE_URL": "https://aiskillstore.io"
      }
    }
  }
}
"""

import sys
import os

# stdlib 'platform' 모듈 충돌 방지: 프로젝트 루트를 sys.path 앞에서 제거 후 mcp 임포트
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_clean_path = [p for p in sys.path if os.path.abspath(p) != _proj_root]
sys.path = _clean_path

from mcp.server.fastmcp import FastMCP
import functools as _functools_tool

def _log_tool(fn):
    """각 MCP tool 호출을 stdout 에 한 줄 기록 — journalctl 에서 grep 가능.
    형식: TOOL_CALL tool=<name> kw=<arg_keys>  (PII 회피 위해 값은 로그 X)
    """
    @_functools_tool.wraps(fn)
    def _wrapper(*args, **kwargs):
        try:
            kw_keys = list(kwargs.keys())
            print(f"TOOL_CALL tool={fn.__name__} kw={kw_keys}", flush=True)
        except Exception:
            pass
        return fn(*args, **kwargs)
    return _wrapper

import urllib.request
import urllib.parse
import urllib.error
import json
import tempfile
from typing import Optional

# 프로젝트 경로 복원 (DB 직접 접근 등 필요 시)
sys.path.insert(0, _proj_root)

# ── 설정 ──────────────────────────────────────────────
SKILL_STORE_URL = os.environ.get("SKILL_STORE_URL", "https://aiskillstore.io")

mcp = FastMCP(
    name="skill-store",
    instructions=(
        "AI Skill Store는 AI 에이전트용 스킬 마켓플레이스입니다.\n"
        "▶ 스킬 탐색: search_skills(capability/platform/키워드) → get_skill_schema(스키마 확인) → download_skill(platform 지정)\n"
        "▶ 스킬 등록 (계정 O): upload_skill(파일+API키) → check_vetting_status / get_vetting_result\n"
        "▶ 스킬 등록 (계정 X, 에이전트 자립): upload_skill_draft(skill_md+X-Agent-Author) → 응답의 claim_url/agent_identity 을 사용자에게 그대로 전달\n"
        "▶ Draft 상태 폴링: check_draft_status(claim_token) — skill-level + agent-level claim 상태 동시 확인\n"
        "▶ Draft 검수 결과 (API 키 없이): get_vetting_result(job_id, claim_token=...) — Draft 업로더 전용 대체 인증\n"
        "▶ Most Wanted: get_most_wanted — 수요만 있고 공급 없는 스킬 (기회)\n"
        "▶ 플랫폼/카테고리: list_platforms, list_categories\n"
        "▶ 설치 가이드: get_install_guide(skill_id, platform)\n"
        "▶ 상세 조회: get_skill(기본 정보), get_skill_schema(호출 스키마)\n"
        "\n"
        "⚠️ Agent Identity (2026-04-23): upload_skill_draft 의 첫 응답에 발급되는 "
        "agent_secret 은 동일 에이전트 이름의 모든 후속 업로드에서 반드시 동일하게 사용해야 합니다. "
        "이 값을 저장/재사용하지 않으면 AGENT_SECRET_REQUIRED / AGENT_SECRET_INVALID 오류로 "
        "업로드가 차단됩니다. 응답의 claim_url / human_action / instruction 은 사용자에게 "
        "반드시 그대로 표시해야 하며, 에이전트가 대신 claim 을 완료하려 해서는 안 됩니다."
    ),
)


# ── 내부 헬퍼 ─────────────────────────────────────────

def _get(path: str, params: dict = None) -> dict:
    url = SKILL_STORE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"status": "error", "message": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _post(path: str, data: dict, headers: dict = None) -> dict:
    url = SKILL_STORE_URL + path
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/json", **(headers or {})},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"status": "error", "message": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _get_auth(path: str, api_key: str, params: dict = None) -> dict:
    """API 키 인증이 필요한 GET 요청."""
    url = SKILL_STORE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"X-API-KEY": api_key})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            body = json.loads(body).get("message", body)
        except Exception:
            pass
        return {"status": "error", "message": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── 툴 정의 ───────────────────────────────────────────

@mcp.tool()
@_log_tool
def search_skills(
    query: str = "",
    capability: str = "",
    platform: str = "",
    min_trust: str = "",
    category: str = "",
    sort: str = "newest",
    limit: int = 20,
) -> str:
    """
    Search skills on AI Skill Store. Use 'capability' or 'platform' params for agent-optimized search (sorted by popularity). Returns skill name, description, downloads, rating, and trust level. / AI Skill Store에서 스킬 검색.
    capability나 platform을 지정하면 에이전트 최적화 검색(인기순 정렬)을 사용합니다.

    Args:
        query: 검색 키워드 (스킬 이름 또는 설명). 비워두면 전체 목록.
        capability: 능력 태그로 검색 (예: web_search, text_summarization, code_generation)
        platform: 특정 플랫폼 호환 스킬만 (OpenClaw, ClaudeCode, ClaudeCodeAgentSkill, Cursor, GeminiCLI, CodexCLI)
        min_trust: 최소 신뢰 등급 (verified > community > sandbox)
        category: 카테고리 필터 (에이전트 검색 미사용 시에만 적용)
        sort: 정렬 기준 (에이전트 검색 미사용 시에만: newest | downloads | rating)
        limit: 결과 수 (기본 20, 최대 50)

    Returns:
        스킬 목록 문자열
    """
    use_agent_api = bool(capability or platform or min_trust)

    if use_agent_api:
        params = {
            "capability": capability or None,
            "q": query or None,
            "platform": platform or None,
            "min_trust": min_trust or None,
            "limit": min(limit, 50),
        }
        result = _get("/v1/agent/search", params)
        if result.get("status") == "error":
            return f"오류: {result.get('message')}"

        skills = result.get("skills", [])
        if not skills:
            return "검색 결과가 없습니다."

        count = result.get("count", len(skills))
        lines = [f"총 {count}개 스킬 (인기순)\n"]
        for s in skills:
            trust_icon = {"verified": "🔒", "community": "🌐", "sandbox": "🔲"}.get(
                s.get("trust_level", ""), "❓"
            )
            caps = ", ".join(s.get("capabilities", [])) or "없음"
            convert = "✅" if s.get("can_auto_convert") else "❌"
            lines.append(
                f"• [{s['skill_id']}] {s['name']} {trust_icon}{s.get('trust_level','')}\n"
                f"  capabilities: {caps}\n"
                f"  다운로드: {s.get('download_count', 0)} | "
                f"자동변환: {convert} | "
                f"v{s.get('version', '')}\n"
                f"  설명: {s.get('description', '')[:80]}"
            )
        return "\n".join(lines)
    else:
        params = {
            "query": query or None,
            "category": category or None,
            "sort": sort,
            "limit": limit,
        }
        result = _get("/v1/skills", params)
        if result.get("status") == "error":
            return f"오류: {result.get('message')}"

        skills = result.get("skills", [])
        total = result.get("total", len(skills))

        if not skills:
            return "검색 결과가 없습니다."

        lines = [f"총 {total}개 스킬\n"]
        for s in skills:
            status_icon = {"approved": "✅", "caution": "⚠️", "rejected": "❌"}.get(
                s.get("vetting_status", ""), "⏳"
            )
            rating = f"⭐{s['avg_rating']:.1f}" if s.get("avg_rating", 0) > 0 else "평점없음"
            lines.append(
                f"• [{s['skill_id']}] {s['name']} {status_icon}\n"
                f"  카테고리: {s.get('category') or '미분류'} | "
                f"다운로드: {s.get('download_count', 0)} | {rating}\n"
                f"  설명: {s['description'][:80]}{'...' if len(s['description']) > 80 else ''}"
            )
        return "\n".join(lines)


@mcp.tool()
@_log_tool
def get_skill(skill_id: str) -> str:
    """
    Get detailed info for a specific skill including description, supported platforms, version history, author, and security vetting status. / 특정 스킬의 상세 정보 조회.

    Args:
        skill_id: 스킬 ID (search_skills 결과의 skill_id)

    Returns:
        스킬 상세 정보 JSON 문자열
    """
    result = _get(f"/v1/skills/{skill_id}")
    if result.get("status") == "error":
        return f"오류: {result.get('message')}"

    skill = result.get("skill", {})
    v = skill.get("latest_version_details") or {}
    tags = v.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [tags]

    lines = [
        f"📦 {skill.get('name')}",
        f"ID: {skill.get('skill_id')}",
        f"설명: {skill.get('description')}",
        f"카테고리: {skill.get('category') or '미분류'}",
        f"소유자: {skill.get('owner_username')}",
        f"버전: {v.get('version_number', 'N/A')}",
        f"보안 상태: {v.get('vetting_status', 'N/A')}",
        f"다운로드: {v.get('download_count', 0)}",
        f"태그: {', '.join(tags) if tags else '없음'}",
        f"등록일: {skill.get('created_at', '')[:10]}",
    ]
    return "\n".join(lines)


@mcp.tool()
@_log_tool
def get_skill_schema(skill_id: str) -> str:
    """
    Get the full schema for invoking a skill - interface spec, input/output schemas, permissions, and capability tags. / 스킬 호출용 전체 스키마 조회.
    인터페이스, 입출력 스키마, 권한, 능력 태그 등을 반환합니다.

    Args:
        skill_id: 스킬 ID

    Returns:
        스킬 호출 스키마 정보
    """
    result = _get(f"/v1/agent/skills/{skill_id}/schema")
    if result.get("status") == "error":
        return f"오류: {result.get('message')}"

    iface = result.get("interface", {})
    perms = result.get("permissions", {})
    caps = result.get("capabilities", [])
    compat = result.get("platform_compatibility", [])
    reqs = result.get("requirements", {})

    lines = [
        f"📋 {result.get('name')} v{result.get('version', '')}",
        f"신뢰: {result.get('trust_level', '')} | "
        f"USK v3: {'✅' if result.get('is_usk_v3') else '❌'} | "
        f"자동변환: {'✅' if result.get('can_auto_convert') else '❌'}",
        "",
        "── Interface ──",
        f"  type: {iface.get('type', 'N/A')}",
        f"  entry_point: {iface.get('entry_point', 'N/A')}",
        f"  runtime: {iface.get('runtime', 'N/A')}",
        f"  call_pattern: {iface.get('call_pattern', 'N/A')}",
        "",
        "── Input Schema ──",
        json.dumps(result.get("input_schema", {}), indent=2, ensure_ascii=False),
        "",
        "── Output Schema ──",
        json.dumps(result.get("output_schema", {}), indent=2, ensure_ascii=False),
        "",
        "── Capabilities ──",
        ", ".join(caps) if caps else "없음",
        "",
        "── Permissions ──",
        f"  network: {perms.get('network', False)}",
        f"  filesystem: {perms.get('filesystem', False)}",
        f"  subprocess: {perms.get('subprocess', False)}",
        f"  env_vars: {', '.join(perms.get('env_vars', [])) or '없음'}",
        "",
        f"플랫폼 호환: {', '.join(compat) if compat else 'any'}",
    ]

    if reqs:
        lines.append("")
        lines.append("── Requirements ──")
        for k, v in reqs.items():
            lines.append(f"  {k}: {v}")

    dl = result.get("download", {})
    if dl.get("platforms"):
        lines.append("")
        lines.append(f"다운로드: download_skill(skill_id=\"{skill_id}\", platform=\"<platform>\")")
        lines.append(f"지원 플랫폼: {', '.join(dl['platforms'])}")

    return "\n".join(lines)


@mcp.tool()
@_log_tool
def download_skill(skill_id: str, platform: str = "", save_dir: str = "") -> str:
    """
    Download a skill package. Specify 'platform' to get an auto-converted package for that platform (ClaudeCode, Cursor, CodexCLI, GeminiCLI, etc.). / 스킬 패키지 다운로드 (플랫폼별 자동 변환).

    Args:
        skill_id: 다운로드할 스킬 ID
        platform: 플랫폼 (OpenClaw, ClaudeCode, ClaudeCodeAgentSkill, CustomAgent, Cursor, GeminiCLI, CodexCLI). 비워두면 원본(.skill) 다운로드.
        save_dir: 저장 디렉터리 경로 (비워두면 임시 디렉터리에 저장)

    Returns:
        저장된 파일 경로 또는 오류 메시지
    """
    url = f"{SKILL_STORE_URL}/v1/agent/skills/{skill_id}/download"
    if platform:
        url += f"?platform={urllib.parse.quote(platform)}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_disposition = resp.headers.get("Content-Disposition", "")
            filename = f"{skill_id}.skill"
            if "filename=" in content_disposition:
                filename = content_disposition.split("filename=")[-1].strip().strip('"')

            fallback = resp.headers.get("X-Fallback-Platform", "")

            target_dir = save_dir if save_dir else tempfile.mkdtemp(prefix="skill_store_")
            os.makedirs(target_dir, exist_ok=True)
            save_path = os.path.join(target_dir, filename)

            with open(save_path, "wb") as f:
                f.write(resp.read())

        msg = f"✅ 다운로드 완료: {save_path}"
        if platform:
            msg += f"\n   플랫폼: {platform}"
        if fallback:
            msg += f"\n   ⚠️ 요청한 플랫폼 변환 불가 → {fallback} 형식으로 대체 제공됨"
        return msg
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
            body = json.loads(body).get("message", body)
        except Exception:
            pass
        return f"❌ 다운로드 실패: HTTP {e.code} — {body or e.reason}"
    except Exception as e:
        return f"❌ 오류: {str(e)}"


@mcp.tool()
@_log_tool
def list_categories() -> str:
    """
    List all available skill categories on AI Skill Store. / AI Skill Store 전체 카테고리 목록.

    Returns:
        카테고리 목록 문자열
    """
    result = _get("/v1/categories")
    if result.get("status") == "error":
        return f"오류: {result.get('message')}"
    categories = result.get("categories", [])
    if not categories:
        return "등록된 카테고리가 없습니다."
    return "사용 가능한 카테고리:\n" + "\n".join(f"• {c}" for c in categories)


@mcp.tool()
@_log_tool
def get_install_guide(skill_id: str, platform: str = "OpenClaw") -> str:
    """
    Get step-by-step installation instructions for a skill on a specific platform. / 플랫폼별 스킬 설치 가이드.

    Args:
        skill_id: 스킬 ID
        platform: 플랫폼 이름 - 'OpenClaw' | 'ClaudeCode' | 'ClaudeCodeAgentSkill' | 'CustomAgent' | 'Cursor' | 'GeminiCLI' | 'CodexCLI'

    Returns:
        단계별 설치 가이드 문자열
    """
    result = _get(f"/v1/skills/{skill_id}/install-guide", {"platform": platform})
    if result.get("status") == "error":
        return f"오류: {result.get('message')}"

    steps = result.get("steps", [])
    lines = [
        f"📋 [{platform}] 설치 가이드 — {result.get('skill_name', skill_id)}",
        f"설정 파일 경로: {result.get('config_path', 'N/A')}",
        "",
        "설치 단계:",
    ]
    for i, step in enumerate(steps, 1):
        if isinstance(step, dict):
            lines.append(f"  {i}. {step.get('description', step)}")
            if step.get("command"):
                lines.append(f"     $ {step['command']}")
        else:
            lines.append(f"  {i}. {step}")
    return "\n".join(lines)


@mcp.tool()
@_log_tool
def upload_skill(
    api_key: str,
    file_path: Optional[str] = None,
    skill_md: Optional[str] = None,
    files: Optional[dict] = None,
    requirements: Optional[str] = None,
    author_agent: Optional[dict] = None,
) -> str:
    """
    Upload a skill package to AI Skill Store. Requires an API key. / 스킬 업로드 (API 키 필요).

    ※ API 키가 없다면 대신 `upload_skill_draft` 를 사용하세요 — 계정 없이 에이전트가 바로
    업로드 가능하며, 이후 사람 owner 가 1회 이메일 인증으로 해당 에이전트의 모든 스킬을
    일괄 claim 할 수 있습니다 (Agent Identity, 2026-04-23).

    **사용 방식 A — JSON content 모드 (에이전트 권장, 디스크 불필요)**:
      - skill_md (필수): SKILL.md 전체 내용 문자열
      - files (선택): {파일명: 파일내용} 딕셔너리. 예: {"main.py": "import sys\\n..."}
      - requirements (선택): requirements.txt 내용 문자열
      - author_agent (선택): {"name": "...", "provider": "..."} 또는 그냥 name 문자열

    **사용 방식 B — 파일 경로 모드 (기존 호환)**:
      - file_path: 업로드할 .skill 파일의 절대 경로

    둘 중 하나만 제공. 둘 다 있으면 JSON content 모드 우선.

    Args:
        api_key: 개발자 API 키 (필수). 없으면 upload_skill_draft 를 사용할 것.
        file_path: (방식 B) .skill 파일 경로
        skill_md: (방식 A) SKILL.md 내용
        files: (방식 A) {파일명: 텍스트내용}
        requirements: (방식 A) requirements.txt 내용
        author_agent: (방식 A) 에이전트 attribution

    Returns:
        업로드 결과 메시지 (version_id, vetting_job_id, poll_url 포함)
    """
    url = f"{SKILL_STORE_URL}/v1/skills/upload"

    # 방식 A: JSON content 모드
    if skill_md:
        payload = {"skill_md": skill_md}
        if files:
            if not isinstance(files, dict):
                return "❌ files는 {파일명: 내용} 딕셔너리여야 합니다."
            payload["files"] = files
        if requirements:
            payload["requirements"] = requirements
        if author_agent:
            payload["author_agent"] = author_agent
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": api_key,
            },
            method="POST",
        )
        mode_label = "json_content"
    # 방식 B: 파일 경로 모드 (호환)
    elif file_path:
        if not os.path.exists(file_path):
            return f"❌ 파일을 찾을 수 없습니다: {file_path}"
        if not file_path.endswith(".skill"):
            return "❌ .skill 파일만 업로드 가능합니다."

        boundary = "----SkillStoreMCPBoundary"
        filename = os.path.basename(file_path)

        with open(file_path, "rb") as f:
            file_data = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="skill_file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            url, data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-API-KEY": api_key,
            },
            method="POST",
        )
        mode_label = "multipart_file"
    else:
        return ("❌ skill_md (방식 A) 또는 file_path (방식 B) 중 하나를 반드시 제공해야 합니다.\n"
                "에이전트는 skill_md + files (딕셔너리) 사용 권장 — 디스크 불필요.")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            vt = data.get("vetting_report", {}).get("status", "pending")
            vid = data.get("version_id", "N/A")
            job = data.get("vetting_job_id") or "N/A"
            poll = data.get("poll_url") or f"{SKILL_STORE_URL}/v1/skills/vetting/{job}"
            return (
                f"✅ 업로드 성공! (mode={mode_label})\n"
                f"스킬: {data.get('skill_name')} v{data.get('version_number')}\n"
                f"버전 ID: {vid}\n"
                f"보안 상태: {vt.upper()}\n"
                f"Vetting Job ID: {job}\n"
                f"폴링 URL: {poll}\n\n"
                f"💡 검수 결과 확인 (권장): get_vetting_result(job_id=\"{job}\", api_key=\"...\")"
            )
    except urllib.error.HTTPError as e:
        body_msg = e.read().decode()
        try:
            err = json.loads(body_msg)
            # RFC 7807 응답이면 error_code + detail 우선
            code = err.get("error_code") or err.get("title") or "HTTP_ERROR"
            msg = err.get("detail") or err.get("message") or body_msg
            return f"❌ 업로드 실패 [{code}]: {msg}"
        except Exception:
            return f"❌ 업로드 실패: {body_msg}"
    except Exception as e:
        return f"❌ 오류: {str(e)}"


@mcp.tool()
@_log_tool
def upload_skill_draft(
    agent_author: str,
    skill_md: str,
    files: Optional[dict] = None,
    requirements: Optional[str] = None,
    contact_email: Optional[str] = None,
    agent_secret: Optional[str] = None,
    claim_token: Optional[str] = None,
) -> str:
    """
    Upload a skill without an API key (zero-friction). Returns a claim_token to track status. Perfect for agents contributing skills autonomously. / API 키 없이 Draft 모드로 스킬 업로드.

    ▶ 정책:
      - AI 검수(approved)만 수락, 그 외(caution/pending/rejected)는 즉시 삭제.
      - 결과는 sandbox tier + claim_status='draft'. 사람 owner 가 claim 해야 community/검증 경로 진입.
      - 동일 agent_author 의 모든 Draft 는 한 번의 이메일 인증으로 일괄 claim 됨.

    ▶ 에이전트 필수 동작(MANDATORY — 무시 시 반복 업로드/인증이 실패):
      (1) 최초 업로드 응답의 agent_identity.agent_secret 값을 반드시 저장하라.
          이후 같은 agent_author 로 업로드할 때 agent_secret 파라미터에 동일 값 전달.
          저장/재사용 안 하면 AGENT_SECRET_REQUIRED(401) 로 차단됨.
      (2) 응답의 claim_url, human_action.instruction, agent_identity 를
          사용자(사람)에게 그대로, 링크 형태로 표시하라 (요약·의역 금지).
      (3) 에이전트가 대신 claim 을 완료하려 하지 말 것. contact_email/verify 메일은
          반드시 사람 owner 의 실제 이메일이어야 함.
      (4) human_action_required=true 이면 사용자 응답을 기다려라 — 자동 재시도 금지.

    Args:
        agent_author: 에이전트 식별자 (X-Agent-Author 헤더로 전송). 예: "claude-sonnet-4-6@anthropic".
                     같은 이름은 agent_secret 으로만 재사용 가능.
        skill_md: SKILL.md 전체 내용 문자열 (필수).
        files: {"main.py": "...", "util.py": "..."} 형태의 부가 파일 dict (선택).
        requirements: requirements.txt 내용 문자열 (선택).
        contact_email: 업로더 사람 owner 의 이메일 (선택, OPTIONAL).
                      ▶ **사용자 이메일을 모르면 반드시 비워두세요** — 추측·생성한 가짜 이메일은
                        DNS resolve 검증(NXDOMAIN 차단)으로 CONTACT_EMAIL_INVALID(400) 거부됩니다.
                      ▶ 비워두면 응답의 claim_url 을 사람 사용자에게 채팅으로 그대로 보여주면 됩니다
                        (forward_claim_url 시나리오, 권장).
                      ▶ 사용자가 명시적으로 알려준 실제 이메일이 있을 때만 지정. 지정 시 서버가
                        verify 링크를 자동 발송 (24시간 만료, 미인증 시 72시간마다 최대 3회 reminder).
                      ▶ 한 번만 지정하면 되며 이후 업로드엔 불필요. verify 링크를 사람이 클릭하면
                        해당 agent_author 의 모든 Draft 가 그 계정으로 일괄 이전.
        agent_secret: 최초 업로드에서 발급된 secret (2회차 이후 필수).
        claim_token: 같은 Draft 에 새 버전을 추가할 때만 (선택).

    Returns:
        업로드 결과 + agent_identity + human_action_required + human_action + claim_url 요약.
        사용자에게 claim_url 과 instruction 을 반드시 surface 하라.
    """
    url = f"{SKILL_STORE_URL}/v1/drafts/upload"

    if not agent_author or not agent_author.strip():
        return "❌ agent_author 는 필수입니다."
    if not skill_md or not skill_md.strip():
        return "❌ skill_md 는 필수입니다."

    payload: dict = {"skill_md": skill_md}
    if files:
        if not isinstance(files, dict):
            return "❌ files 는 {파일명: 내용} 딕셔너리여야 합니다."
        payload["files"] = files
    if requirements:
        payload["requirements"] = requirements
    if contact_email:
        payload["contact_email"] = contact_email
    if claim_token:
        payload["claim_token"] = claim_token

    headers = {
        "Content-Type": "application/json",
        "X-Agent-Author": agent_author.strip(),
    }
    if agent_secret:
        headers["X-Agent-Secret"] = agent_secret.strip()

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_msg = e.read().decode()
        try:
            err = json.loads(body_msg)
            code = err.get("error_code") or err.get("title") or "HTTP_ERROR"
            msg = err.get("detail") or err.get("message") or body_msg
            hint = ""
            if code in ("AGENT_SECRET_REQUIRED", "AGENT_SECRET_INVALID"):
                hint = ("\n⚠️ 최초 업로드 응답의 agent_identity.agent_secret 을 반드시 "
                        "재사용하세요. 저장된 값이 없다면 다른 agent_author 를 사용해야 합니다.")
            return f"❌ Draft 업로드 실패 [{code}]: {msg}{hint}"
        except Exception:
            return f"❌ Draft 업로드 실패: {body_msg}"
    except Exception as e:
        return f"❌ 오류: {str(e)}"

    ident = data.get("agent_identity") or {}
    human = data.get("human_action") or {}
    lines = [
        f"✅ Draft 업로드 성공 — {data.get('skill_name')} v{data.get('version_number')}",
        f"skill_id:       {data.get('skill_id')}",
        f"trust_level:    {data.get('trust_level')} (claim 전까지)",
        f"claim_token:    {data.get('claim_token')}",
        f"claim_url:      {data.get('claim_url')}",
        f"expires_at:     {data.get('expires_at')}",
    ]
    if data.get("vetting_job_id"):
        lines.append(f"vetting_job_id: {data.get('vetting_job_id')}  "
                     f"(폴링: get_vetting_result)")

    # Agent Identity block
    lines.append("")
    lines.append("── Agent Identity ──")
    lines.append(f"  is_new: {ident.get('is_new')}")
    if ident.get("agent_secret"):
        lines.append(f"  agent_secret: {ident['agent_secret']}")
        lines.append("  ⚠️ 이 값을 반드시 저장하라. 같은 agent_author 의 다음 업로드부터 agent_secret 파라미터에 그대로 사용.")
    lines.append(f"  contact_email:          {ident.get('contact_email') or '(없음)'}")
    lines.append(f"  contact_email_verified: {ident.get('contact_email_verified')}")
    lines.append(f"  claimed:                {ident.get('claimed')}")
    lines.append(f"  verify_email_sent:      {ident.get('verify_email_sent')}")

    # Human action surface (D1) — MUST show to user verbatim
    if data.get("human_action_required"):
        lines.append("")
        lines.append("── ⚠️ HUMAN ACTION REQUIRED (사용자에게 그대로 표시) ──")
        lines.append(f"  action:   {human.get('type')}")
        lines.append(f"  deadline: {human.get('deadline')}")
        if human.get("contact_email"):
            lines.append(f"  email:    {human['contact_email']}")
        lines.append(f"  claim_url: {human.get('claim_url')}")
        lines.append(f"  instruction: {human.get('instruction')}")
        lines.append("")
        lines.append("  ℹ️ 위 claim_url 을 사용자에게 링크 형태로 그대로 전달하세요. "
                     "에이전트가 대신 claim 을 완료해서는 안 됩니다.")

    return "\n".join(lines)


@mcp.tool()
@_log_tool
def check_draft_status(claim_token: str) -> str:
    """
    Check the status of a draft skill upload using a claim_token. / Draft 스킬 상태 공개 조회.

    사용 시점:
      - 사람이 claim_url 을 클릭해서 인증을 끝냈는지 확인
      - contact_email 로 보낸 agent-level verify 메일이 처리됐는지 확인
      - Draft 가 30일 안에 claim 됐는지 / 만료됐는지 확인

    Args:
        claim_token: upload_skill_draft 응답의 claim_token

    Returns:
        상태 요약 (claimed, expired, agent_verify_email_sent, agent_claimed 등).
    """
    if not claim_token or not claim_token.strip():
        return "❌ claim_token 은 필수입니다."
    import urllib.parse as _up
    result = _get(f"/v1/drafts/status?claim_token={_up.quote(claim_token.strip())}")
    if result.get("status") == "error" or result.get("error_code"):
        code = result.get("error_code") or "ERROR"
        msg = result.get("detail") or result.get("message") or "조회 실패"
        return f"❌ [{code}]: {msg}"

    claimed = bool(result.get("claimed"))
    expired = bool(result.get("expired"))
    agent_claimed = bool(result.get("agent_claimed"))
    icon = "✅" if claimed else ("⏳" if not expired else "⌛")

    lines = [
        f"{icon} Draft 상태 — {result.get('skill_name')}",
        f"  skill_id:                 {result.get('skill_id')}",
        f"  draft_agent_author:       {result.get('draft_agent_author')}",
        f"  created_at:               {result.get('created_at')}",
        f"  expires_at:               {result.get('expires_at')}",
        f"  claimed (skill-level):    {claimed}{' at ' + result['claimed_at'] if claimed else ''}",
        f"  expired:                  {expired}",
        f"  verify_email_sent:        {result.get('verify_email_sent')}  (skill-level 1:1 legacy)",
        f"  agent_verify_email_sent:  {result.get('agent_verify_email_sent')}  (agent-level, 2026-04-23)",
        f"  agent_claimed:            {agent_claimed}  (agent identity 이미 계정에 귀속)",
    ]
    if not claimed and not expired and not agent_claimed:
        lines.append("  ⏳ 아직 사람이 claim 하지 않았습니다. claim_url 을 사용자에게 전달했는지 확인하세요.")
    if agent_claimed and not claimed:
        lines.append("  ℹ️ agent-level claim 은 완료됐으나 이 특정 Draft 는 아직 이전 안 됐을 수 있음 — "
                     "vetting 완료 후 자동으로 owner 계정에 귀속됩니다.")
    return "\n".join(lines)


@mcp.tool()
@_log_tool
def get_agent_identity_stats(agent_name: str) -> str:
    """
    Get identity stats for the calling agent - claim success rate, claimed/expired counts. / 에이전트 단위 claim 통계.
    특정 agent_author 가 업로드한 Draft 들의 claim_success_rate / expire_rate 를 공개 조회.

    Args:
        agent_name: 에이전트 이름 (X-Agent-Author 와 동일)

    Returns:
        total_uploads, total_claimed, total_expired, claim_success_rate, contact_email_verified 요약.
    """
    result = _get(f"/v1/agent-authors/{agent_name}/identity-stats")
    if result.get("status") == "error" or result.get("error_code"):
        code = result.get("error_code") or "ERROR"
        msg = result.get("detail") or result.get("message") or "조회 실패"
        return f"❌ [{code}]: {msg}"
    stats = result.get("stats") or result
    return (
        f"Agent Identity: {stats.get('agent_author')}\n"
        f"  total_uploads:        {stats.get('total_uploads')}\n"
        f"  total_claimed:        {stats.get('total_claimed')}\n"
        f"  total_expired:        {stats.get('total_expired')}\n"
        f"  claim_success_rate:   {stats.get('claim_success_rate')}\n"
        f"  contact_email_verified: {stats.get('contact_email_verified')}\n"
        f"  claimed:              {stats.get('claimed')}\n"
        f"  first_upload_at:      {stats.get('first_upload_at', '—')}"
    )


@mcp.tool()
@_log_tool
def check_vetting_status(version_id: str, api_key: str) -> str:
    """
    Check the security vetting status of an uploaded skill version. / 업로드 스킬의 보안 검수 상태 확인.
    upload_skill 결과에서 받은 version_id와 API 키가 필요합니다.

    Args:
        version_id: 스킬 버전 ID (upload_skill 결과의 version_id 또는 vetting_job_id)
        api_key: 개발자 API 키 (스킬 소유자만 조회 가능)

    Returns:
        검수 상태 메시지
    """
    result = _get_auth(f"/v1/skills/versions/{version_id}/vetting-status", api_key)
    if result.get("status") == "error":
        return f"❌ 조회 실패: {result.get('message')}"

    vetting = result.get("vetting_status", "unknown")
    status_icon = {
        "approved": "✅ 승인",
        "officially_approved": "✅ 공식 승인",
        "caution": "⚠️ 주의 (수동 검토 필요)",
        "rejected": "❌ 거부",
        "pending": "⏳ 검수 중",
    }.get(vetting, f"❓ {vetting}")

    lines = [
        f"검수 상태: {status_icon}",
        f"버전 ID: {version_id}",
    ]

    if result.get("job_id"):
        lines.append(f"Job ID: {result['job_id']}")
        lines.append(f"Job 상태: {result.get('job_status', 'N/A')}")
    if result.get("started_at"):
        lines.append(f"시작: {result['started_at']}")
    if result.get("finished_at"):
        lines.append(f"완료: {result['finished_at']}")
    if result.get("error_msg"):
        lines.append(f"오류: {result['error_msg']}")

    return "\n".join(lines)


@mcp.tool()
@_log_tool
def get_vetting_result(job_id: str, api_key: str = "", claim_token: str = "") -> str:
    """
    Get the detailed security vetting report for a skill (poll by job_id, claim_token supported). / 보안 검수 결과 상세 조회.
    업로드 응답의 vetting_job_id 로 검수 결과를 폴링합니다.
    에이전트가 이메일 없이 HTTP만으로 최종 결과를 받는 공식 권장 경로.

    ▶ 인증 (둘 중 하나):
      - api_key: 회원 계정의 API 키 (upload_skill 경로 업로더)
      - claim_token: Draft Upload(upload_skill_draft) 응답의 claim_token.
        API 키 없는 에이전트는 이 토큰으로 자신의 검수 결과를 폴링 가능.

    반환 메시지에는 is_done 플래그, vetting_status, findings[] 가 포함됩니다.
    is_done=false 면 몇 초 후 다시 호출하세요 (보통 검수는 수 초~수십 초 소요).

    Args:
        job_id: upload_skill / upload_skill_draft 응답의 vetting_job_id
        api_key: 개발자 API 키 (업로더 본인만 조회 가능). 없으면 claim_token 필수.
        claim_token: Draft Upload 응답의 claim_token (api_key 대안).

    Returns:
        검수 결과 메시지 (is_done 여부 + 결과 포함)
    """
    if not api_key and not claim_token:
        return "❌ api_key 또는 claim_token 중 하나를 반드시 제공하세요."

    # claim_token 경로: 인증 헤더 없이 query 파라미터로 전달
    if not api_key and claim_token:
        import urllib.parse as _up
        path = f"/v1/skills/vetting/{job_id}?claim_token={_up.quote(claim_token)}"
        result = _get(path)
        if result.get("status") == "error" or result.get("error_code"):
            code = result.get("error_code") or "ERROR"
            msg = result.get("detail") or result.get("message") or "조회 실패"
            return f"❌ [{code}]: {msg}"
    else:
        result = _get_auth(f"/v1/skills/vetting/{job_id}", api_key)
    if result.get("status") == "error" or result.get("error_code"):
        code = result.get("error_code") or "ERROR"
        msg = result.get("detail") or result.get("message") or "알 수 없는 오류"
        return f"❌ 조회 실패 [{code}]: {msg}"

    is_done = bool(result.get("is_done"))
    vs = result.get("vetting_status") or "unknown"
    js = result.get("job_status") or "unknown"
    icon = "✅" if vs in ("approved", "officially_approved") else ("❌" if vs in ("rejected", "officially_rejected") else ("⚠️" if vs == "caution" else "⏳"))

    lines = [
        f"{icon} 검수 결과 (is_done={is_done})",
        f"Job ID: {result.get('job_id')}",
        f"Version ID: {result.get('version_id')}",
        f"Job 상태: {js}",
        f"Vetting 상태: {vs}",
    ]
    if result.get("started_at"):
        lines.append(f"시작: {result['started_at']}")
    if result.get("finished_at"):
        lines.append(f"완료: {result['finished_at']}")
    if result.get("summary"):
        lines.append(f"요약: {result['summary']}")
    findings = result.get("findings") or []
    if findings:
        lines.append(f"\n발견 사항 ({len(findings)}건):")
        for i, f in enumerate(findings[:10], 1):
            code = f.get("code") or "-"
            sev = f.get("severity") or ""
            m = f.get("message") or ""
            lines.append(f"  {i}. [{code}] {sev} {m}")
    if result.get("error_msg"):
        lines.append(f"오류: {result['error_msg']}")
    if not is_done:
        lines.append("\n⏳ 아직 진행 중입니다. 몇 초 후 다시 호출하세요.")

    return "\n".join(lines)


@mcp.tool()
@_log_tool
def register_developer(username: str, email: str) -> str:
    """
    Register a developer account on AI Skill Store. API key is issued after email verification. / 개발자 계정 등록.
    이메일 인증 후 API 키가 발급됩니다 (보안을 위해 즉시 발급되지 않음).

    Args:
        username: 사용할 username (영문/숫자, 3자 이상, 중복 불가)
        email: 인증용 이메일 주소 (필수 — 인증 링크가 발송됨)

    Returns:
        등록 결과 메시지. 이메일 인증 후 API 키를 받을 수 있습니다.
    """
    payload = {"username": username, "email": email}

    result = _post("/v1/owners/register", payload)

    status = result.get("status", "")
    if status == "pending_verification":
        return (
            f"✅ 계정 등록 완료! 이메일 인증이 필요합니다.\n"
            f"username : {username}\n"
            f"owner_id : {result.get('owner_id', 'N/A')}\n\n"
            f"📧 {email} 으로 인증 메일이 발송되었습니다.\n"
            f"이메일의 인증 링크를 클릭하면 API 키가 발급됩니다.\n"
            f"발급된 API 키로 upload_skill을 호출할 수 있습니다."
        )
    elif status == "success":
        # 이메일 인증이 불필요한 경우 (향후 변경될 수 있음)
        return (
            f"✅ 계정 등록 성공!\n"
            f"username : {result.get('username', username)}\n"
            f"owner_id : {result.get('owner_id')}\n"
            f"api_key  : {result.get('api_key')}\n\n"
            f"⚠️  api_key는 다시 조회할 수 없습니다. 반드시 지금 저장하세요.\n"
            f"이 api_key를 upload_skill 호출 시 사용하세요."
        )
    else:
        msg = result.get("message", str(result))
        return f"❌ 등록 실패: {msg}"


@mcp.tool()
@_log_tool
def validate_compatibility(
    skill_id: str,
    python_version: str = "",
    os: str = "",
    installed_packages: dict = None,
    target_platform: str = "",
) -> str:
    """
    Check if a skill is compatible with a specific platform before downloading. / 다운로드 전 호환성 검증.
    requirements(python/packages)와 platform_compatibility 기준으로 compatible 여부를 반환.

    Args:
        skill_id: 검증할 스킬 ID
        python_version: 에이전트 Python 버전 (예: "3.11.2")
        os: "linux" | "darwin" | "windows"
        installed_packages: {"requests": "2.31.0"} 형태 dict (선택)
        target_platform: 설치 대상 플랫폼 ("ClaudeCode" 등)

    Returns:
        요약 문자열 (compatible 여부 + 누락 패키지 + 추천 설치 명령)
    """
    import requests as _rq
    if installed_packages is None:
        installed_packages = {}
    payload = {}
    if python_version: payload['python_version'] = python_version
    if os: payload['os'] = os
    if installed_packages: payload['installed_packages'] = installed_packages
    if target_platform: payload['target_platform'] = target_platform

    url = f"{SKILL_STORE_URL}/v1/skills/{skill_id}/validate"
    try:
        r = _rq.post(url, json=payload, timeout=15)
    except Exception as e:
        return f"❌ 요청 실패: {e}"

    if r.status_code == 404:
        return "❌ 스킬을 찾을 수 없음"
    if r.status_code != 200:
        try: err = r.json().get('detail') or r.json().get('message') or r.text[:200]
        except Exception: err = r.text[:200]
        return f"❌ 검증 실패 ({r.status_code}): {err}"

    d = r.json()
    compat = "✅ 호환" if d.get('compatible') else "❌ 비호환"
    lines = [f"{compat}  {d.get('skill_name')} v{d.get('version')}"]
    for check in d.get('checks', []):
        nm = check.get('name')
        status = check.get('status')
        icon = {'ok':'✅','not_specified':'⚪','informational':'ℹ️','unknown':'⚪','mismatch':'❌','missing':'❌','unsupported':'❌'}.get(status, '•')
        if nm == 'packages':
            miss = check.get('missing') or []
            vmm = check.get('version_mismatch') or []
            sat = check.get('satisfied') or []
            lines.append(f"  {icon} packages: satisfied={len(sat)}, missing={len(miss)}, mismatch={len(vmm)}")
            for m in miss[:5]:
                lines.append(f"      - missing: {m['name']} {m.get('required','')}")
            for vm in vmm[:5]:
                lines.append(f"      - mismatch: {vm['name']} req={vm['required']} installed={vm['installed']}")
        else:
            lines.append(f"  {icon} {nm}: {status}  ({check.get('message','')[:80]})")
    sugg = d.get('suggested_install_commands') or []
    if sugg:
        lines.append("  추천 설치:")
        for s in sugg[:8]:
            lines.append(f"    $ {s}")
    warns = d.get('warnings') or []
    if warns:
        lines.append("  경고:")
        for w in warns:
            lines.append(f"    ⚠️ {w}")
    return "\n".join(lines)


@mcp.tool()
@_log_tool
def post_review(skill_id: str, rating: int, comment: str = "", api_key: str = "") -> str:
    """
    Post a review and rating for a skill. / 스킬 리뷰 작성.

    정책:
    - 한 사용자가 같은 스킬에 최대 1개 리뷰 (재호출 시 수정)
    - 본인이 등록한 스킬에는 리뷰 작성 불가
    - Rate limit: 10회/시간/IP

    Args:
        skill_id: 리뷰할 스킬 ID
        rating: 평점 (1~5 정수)
        comment: 코멘트 (선택, 최대 2000자)
        api_key: 개발자/에이전트 API 키 (필수)

    Returns:
        결과 메시지
    """
    import requests
    if not api_key:
        return "❌ api_key는 필수입니다. register_developer로 발급받으세요."
    if not isinstance(rating, int) or not 1 <= rating <= 5:
        return "❌ rating은 1~5 사이 정수여야 합니다."
    if comment and len(comment) > 2000:
        return "❌ comment는 최대 2000자까지 입력할 수 있습니다."

    url = f"{SKILL_STORE_URL}/v1/skills/{skill_id}/reviews"
    headers = {
        "X-API-KEY": api_key,
        "X-Reviewer-Type": "agent",
        "Content-Type": "application/json",
    }
    payload = {"rating": rating}
    if comment:
        payload["comment"] = comment

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
    except requests.RequestException as e:
        return f"❌ 요청 실패: {e}"

    if resp.status_code in (200, 201):
        data = resp.json()
        action = data.get("action", "created")
        if action == "updated":
            return (
                f"✅ 리뷰가 수정되었습니다.\n"
                f"review_id    : {data.get('review_id')}\n"
                f"skill_id     : {skill_id}\n"
                f"rating       : {rating}\n"
                f"reviewer_type: agent"
            )
        return (
            f"✅ 리뷰가 등록되었습니다.\n"
            f"review_id    : {data.get('review_id')}\n"
            f"skill_id     : {skill_id}\n"
            f"rating       : {rating}\n"
            f"reviewer_type: agent"
        )

    try:
        err = resp.json().get("message", resp.text[:200])
    except Exception:
        err = resp.text[:200]
    if resp.status_code == 401:
        return f"❌ 인증 실패 (401): {err}"
    if resp.status_code == 403:
        return f"❌ 금지됨 (403): {err}"
    if resp.status_code == 429:
        return f"❌ Rate limit 초과 (429): 시간당 10회 제한"
    return f"❌ 리뷰 등록 실패 ({resp.status_code}): {err}"


@mcp.tool()
@_log_tool
def list_platforms() -> str:
    """
    List all supported platforms (ClaudeCode, Cursor, CodexCLI, GeminiCLI, OpenClaw, CustomAgent, etc.). / 지원 플랫폼 목록.

    Returns:
        플랫폼 목록 문자열
    """
    result = _get("/v1/platforms")
    if result.get("status") == "error":
        return f"오류: {result.get('message')}"
    platforms = result.get("platforms", [])
    if not platforms:
        return "등록된 플랫폼이 없습니다."
    lines = ["지원 플랫폼:"]
    for p in platforms:
        lines.append(f"• {p.get('name')} — {p.get('description', '')}")
    return "\n".join(lines)


@mcp.tool()
@_log_tool
def get_most_wanted(days: int = 30, limit: int = 20, type: str = "all") -> str:
    """
    Get the list of most-wanted skills that haven't been built yet (Supply Loop). Agents can build these to fill community demand. / 미공급 수요 스킬 목록 (Most Wanted).
    0건 검색 쿼리를 집계한 결과 — 여기 올라온 스킬을 만들어 업로드하면 즉시 다운로드 수요 있음.

    Args:
        days: 최근 N일 (기본 30, 최대 365)
        limit: 최대 반환 개수 (기본 20, 최대 100)
        type: 'keyword' | 'capability' | 'all'

    Returns:
        수요 랭킹을 요약한 문자열. 각 항목: query, query_type, zero_result_count, last_seen.
    """
    if type not in ("keyword", "capability", "all"):
        type = "all"
    result = _get("/v1/demand/most-wanted", params={"days": days, "limit": limit, "type": type})
    if result.get("status") == "error":
        return f"오류: {result.get('message')}"
    items = result.get("items", [])
    if not items:
        return "아직 누적된 0-건 검색 신호가 없습니다. 데이터 축적 중."
    lines = [f"Most Wanted — 최근 {days}일 누적 (type={type}, {len(items)}건):"]
    for i, it in enumerate(items, 1):
        lines.append(
            f"{i:>2}. [{it['query_type']}] \"{it['query']}\" × {it['zero_result_count']}"
            f" (last: {it.get('last_seen', '')[:10]})"
        )
    lines.append("")
    lines.append("만들어서 업로드 가이드: " + SKILL_STORE_URL + "/guide/usk")
    lines.append("업로드 시 X-Agent-Author 헤더로 attribution 기록 가능.")
    return "\n".join(lines)


@mcp.tool()
@_log_tool
def get_agent_author_stats(agent_name: str) -> str:
    """
    Get contribution stats for an agent author - uploads, claims, attribution history. / 에이전트 빌더 기여 통계.

    Args:
        agent_name: 에이전트 이름 (예: "claude-sonnet-4-6")

    Returns:
        skills_count, total_downloads, downloads_7d, avg_rating, top_categories 요약.
    """
    result = _get(f"/v1/agent-authors/{agent_name}/stats")
    if result.get("status") == "error":
        return f"오류: {result.get('message')}"
    s = result.get("stats", {})
    if s.get("skills_count", 0) == 0:
        return f"에이전트 '{agent_name}' 은(는) 아직 업로드한 스킬이 없습니다."
    return (
        f"Agent: {s['name']}\n"
        f"  Skills published: {s['skills_count']}\n"
        f"  Total downloads:  {s['total_downloads']}\n"
        f"  Downloads (7d):   {s['downloads_7d']}\n"
        f"  Avg rating:       {s['avg_rating']}\n"
        f"  Top categories:   {', '.join(s['top_categories']) if s['top_categories'] else '—'}\n"
        f"  Latest skill at:  {s.get('latest_skill_packaged_at', '—')}"
    )


# ── 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"AI Skill Store MCP Server 시작 (연결 대상: {SKILL_STORE_URL})")
    mcp.run()
