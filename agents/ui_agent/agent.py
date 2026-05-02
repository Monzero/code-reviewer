from __future__ import annotations
import asyncio
import json
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from core.llm.base import LLMClient
from core.audit.models import (
    AgentResultOk, AgentResultFailed, LLMMeta, TokenUsage
)
from core.observability.logger import get_logger

PROMPT_VERSION = "ui_v1.0"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"


def _fetch_ui(ui_url: str) -> tuple[int, str, str]:
    """Return (status_code, page_title, html_summary). Status 0 means unreachable."""
    try:
        resp = requests.get(ui_url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else "No title"
        headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])[:10]]
        links = [a.get("href", "") for a in soup.find_all("a", href=True)[:20]]
        forms = len(soup.find_all("form"))
        inputs = len(soup.find_all("input"))
        buttons = len(soup.find_all("button"))
        summary = (
            f"Headings: {headings}\n"
            f"Links ({len(links)}): {links[:8]}\n"
            f"Forms: {forms}, Inputs: {inputs}, Buttons: {buttons}"
        )
        return resp.status_code, title, summary
    except Exception as exc:
        return 0, "", f"Unreachable: {exc}"


class UIAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self._prompt_template = _PROMPT_PATH.read_text()

    async def run(
        self,
        project_name: str,
        ui_url: str,
        file_contents: list[str] | None = None,
    ) -> AgentResultOk | AgentResultFailed:
        log = get_logger().bind(agent="ui", prompt_version=PROMPT_VERSION)

        # Fetch live page if URL provided
        status_code, page_title, html_summary = 0, "", ""
        if ui_url:
            status_code, page_title, html_summary = await asyncio.to_thread(
                _fetch_ui, ui_url
            )
            if status_code == 0:
                log.warning("ui_url_unreachable", ui_url=ui_url)

        live_reachable = ui_url and status_code not in (0,)
        has_sources = bool(file_contents)

        # Build prompt sections based on what's available
        if ui_url and status_code != 0:
            live_data_section = (
                f"Live Deployment\n"
                f"URL: {ui_url}\n"
                f"HTTP Status: {status_code}\n"
                f"Page Title: {page_title}\n\n"
                f"Page Structure:\n---\n{html_summary}\n---"
            )
        elif ui_url and status_code == 0:
            live_data_section = (
                f"Live Deployment\n"
                f"URL: {ui_url}\n"
                f"Status: UNREACHABLE — the deployment URL could not be fetched."
            )
        else:
            live_data_section = "Live Deployment: No deployment URL provided."

        if has_sources:
            joined = "\n\n".join(file_contents)
            source_files_section = f"Frontend Source Files:\n---\n{joined}\n---"
        else:
            source_files_section = "Frontend Source Files: None available."

        if live_reachable and has_sources:
            evaluation_note = (
                "You have both live deployment data and source code. "
                "Weight the live page structure heavily for accessibility and completeness checks; "
                "use source code to fill gaps and understand intent."
            )
        elif has_sources:
            evaluation_note = (
                "The deployment is not available. Base your entire evaluation on the source code. "
                "Infer the UI structure, flows, and completeness from the frontend files. "
                "Set confidence to 'medium' at most since you cannot observe the running UI."
            )
        else:
            evaluation_note = (
                "Neither a live deployment nor source files are available. "
                "Score 0 with low confidence."
            )

        prompt = self._prompt_template.format(
            project_name=project_name,
            live_data_section=live_data_section,
            source_files_section=source_files_section,
            evaluation_note=evaluation_note,
        )

        log.info("llm_call_start", has_live=live_reachable, has_sources=has_sources)
        try:
            llm_resp = await self.llm.generate(prompt)
        except Exception as exc:
            log.error("llm_call_failed", error=str(exc))
            return AgentResultFailed(error=str(exc))

        log.info("llm_call_end", latency_ms=llm_resp.latency_ms,
                 tokens_output=llm_resp.tokens_output)
        try:
            parsed = json.loads(llm_resp.text)
            return AgentResultOk(
                score=float(parsed["score"]),
                reasoning=parsed["reasoning"],
                confidence=parsed["confidence"],
                llm=LLMMeta(
                    provider=self.llm.provider,
                    model=self.llm.model,
                    model_version=llm_resp.model_version,
                ),
                prompt_version=PROMPT_VERSION,
                tokens=TokenUsage(
                    input=llm_resp.tokens_input, output=llm_resp.tokens_output
                ),
                latency_ms=llm_resp.latency_ms,
                raw_llm_response=llm_resp.text,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            log.error("parse_failed", error=str(exc))
            return AgentResultFailed(error=f"Failed to parse LLM response: {exc}")
