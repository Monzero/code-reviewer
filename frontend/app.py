"""Streamlit judge interface for the AI Project Evaluator."""
import streamlit as st
import requests as http

import os
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pdf_report import generate_pdf
API_BASE = os.getenv("API_BASE", "http://localhost:8000")


def render_agent_analysis(agents: dict) -> None:
    """Render per-agent reasoning and code sub-scores."""
    st.subheader("Agent Analysis")
    for agent_name in ("objective", "code", "ui"):
        result = agents.get(agent_name, {})
        with st.expander(f"{agent_name.title()} Agent", expanded=True):
            if result.get("status") == "failed":
                st.error(f"Agent failed: {result.get('error', 'unknown error')}")
                continue

            st.markdown(f"**Score:** {result.get('score')}/10  \n"
                        f"**Confidence:** {result.get('confidence', '—')}")
            st.markdown(f"**Reasoning:** {result.get('reasoning', '—')}")

            if agent_name == "code" and result.get("sub_scores"):
                st.markdown("**Sub-dimension scores:**")
                rows = []
                for dim, sub in result["sub_scores"].items():
                    rows.append({
                        "Dimension": dim.replace("_", " ").title(),
                        "Score": f"{sub['score']}/10",
                        "Reasoning": sub["reasoning"],
                    })
                st.table(rows)

def render_interview_guide(agents: dict) -> None:
    """Render ownership agent's key decisions and interview questions."""
    ownership = agents.get("ownership", {})
    if not ownership or ownership.get("status") == "failed":
        return
    key_decisions = ownership.get("key_decisions", [])
    if not key_decisions:
        return
    st.subheader("Interview Guide")
    st.caption(
        f"Ownership score: **{ownership.get('score')}/10** "
        f"(confidence: {ownership.get('confidence', '—')})  \n"
        f"{ownership.get('reasoning', '')}"
    )
    for i, kd in enumerate(key_decisions, 1):
        with st.expander(f"Q{i}: {kd['decision']}", expanded=True):
            st.markdown(f"**Signal observed:** {kd['ownership_signal']}")
            st.info(f"**Ask:** {kd['question']}")


st.set_page_config(page_title="AI Project Evaluator", layout="wide")


# ── Auth ──────────────────────────────────────────────────────────────────────

def login(username: str, password: str) -> str | None:
    resp = http.post(f"{API_BASE}/auth/token",
                     json={"username": username, "password": password})
    if resp.status_code == 200:
        return resp.json()["access_token"]
    return None


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


if "token" not in st.session_state:
    st.session_state.token = None

if not st.session_state.token:
    st.title("Judge Login")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            token = login(username, password)
            if token:
                st.session_state.token = token
                st.session_state.username = username
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.stop()


# ── Sidebar navigation ────────────────────────────────────────────────────────

st.sidebar.title("AI Project Evaluator")
st.sidebar.caption(f"Logged in as **{st.session_state.get('username', '')}**")
page = st.sidebar.radio(
    "Navigate",
    ["Submit Evaluation", "View Report", "Evaluation History", "Metrics"],
)
if st.sidebar.button("Logout"):
    st.session_state.token = None
    st.rerun()


# ── Submit Evaluation ─────────────────────────────────────────────────────────

if page == "Submit Evaluation":
    st.title("Submit Evaluation")
    with st.form("evaluate"):
        project_name = st.text_input("Project Name")
        participant = st.text_input("Participant Name")
        objective = st.text_area("Stated Objective", height=100)
        repo_url = st.text_input("GitHub Repository URL")
        ui_url = st.text_input(
            "UI / Deployment URL (optional — leave blank for local/undeployed projects)"
        )
        submitted = st.form_submit_button("Run Evaluation")

    if submitted:
        if not all([project_name, participant, objective, repo_url]):
            st.error("Project name, participant, objective, and repo URL are required.")
        else:
            with st.spinner("Running evaluation (this may take ~30s)…"):
                resp = http.post(
                    f"{API_BASE}/evaluate",
                    json={
                        "project_name": project_name,
                        "participant": participant,
                        "objective": objective,
                        "repo_url": repo_url,
                        "ui_url": ui_url,
                    },
                    headers=auth_headers(),
                    timeout=120,
                )
            if resp.status_code == 200:
                data = resp.json()
                eval_id = data["evaluation_id"]
                report = data["report"]
                st.success(f"Evaluation complete — ID: `{eval_id}`")
                st.session_state.last_eval_id = eval_id

                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("Overall", f"{report['overall_score']}/10")
                col2.metric("Objective", f"{report['objective_score']}/10")
                col3.metric("Code", f"{report['code_score']}/10")
                col4.metric("UI", f"{report['ui_score']}/10")
                ownership_score = report.get("ownership_score")
                col5.metric("Ownership", f"{ownership_score}/10" if ownership_score is not None else "—")

                if report["flags"]:
                    st.warning("Flags: " + ", ".join(f"`{f}`" for f in report["flags"]))
                st.info(report["summary"])
                if data.get("agents"):
                    render_agent_analysis(data["agents"])
                    render_interview_guide(data["agents"])
                pdf_bytes = generate_pdf(
                    evaluation_id=eval_id,
                    report=report,
                    agents=data.get("agents"),
                )
                st.download_button(
                    label="Download PDF Report",
                    data=pdf_bytes,
                    file_name=f"evaluation_{eval_id}.pdf",
                    mime="application/pdf",
                )
                st.caption(f"View full report → **View Report** tab using ID `{eval_id}`")
            else:
                st.error(f"Error {resp.status_code}: {resp.text}")


# ── View Report ───────────────────────────────────────────────────────────────

elif page == "View Report":
    st.title("Evaluation Report")
    eval_id = st.text_input(
        "Evaluation ID",
        value=st.session_state.get("last_eval_id", ""),
    )

    if eval_id and st.button("Load Report"):
        resp = http.get(f"{API_BASE}/report/{eval_id}", headers=auth_headers())
        prov_resp = http.get(f"{API_BASE}/report/{eval_id}/provenance", headers=auth_headers())

        if resp.status_code != 200:
            st.error(f"Not found: {eval_id}")
        else:
            data = resp.json()
            report = data["aggregated"]
            snap = data["input_snapshot"]
            overrides = data["judge_overrides"]
            prov = prov_resp.json() if prov_resp.status_code == 200 else {}

            # Scores
            st.subheader("Scores")
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Overall", f"{report['overall_score']}/10")
            col2.metric("Objective", f"{report['objective_score']}/10")
            col3.metric("Code", f"{report['code_score']}/10")
            col4.metric("UI", f"{report['ui_score']}/10")
            ownership_score = report.get("ownership_score")
            col5.metric("Ownership", f"{ownership_score}/10" if ownership_score is not None else "—")

            if report["flags"]:
                st.warning("Flags: " + ", ".join(f"`{f}`" for f in report["flags"]))

            # Provenance
            st.subheader("Provenance")
            st.markdown(f"""
| Field | Value |
|---|---|
| Evaluation ID | `{eval_id}` |
| Triggered by | {data['triggered_by']} |
| Created at | {data['created_at']} |
| Repo | {snap['repo_url']} |
| Commit SHA | `{snap['repo_commit_sha']}` |
| UI URL | {snap['ui_url']} |
""")
            if prov.get("agents"):
                st.subheader("Per-Agent LLM Details")
                for agent_name, agent_prov in prov["agents"].items():
                    with st.expander(agent_name.title()):
                        if agent_prov.get("status") == "failed":
                            st.error(agent_prov.get("error"))
                        else:
                            st.json(agent_prov)

            # Agent analysis (reasoning + sub-scores)
            if data.get("agents"):
                render_agent_analysis(data["agents"])
                render_interview_guide(data["agents"])

            # PDF download
            pdf_bytes = generate_pdf(
                evaluation_id=eval_id,
                report=report,
                agents=data.get("agents"),
                data=data,
                prov=prov,
            )
            st.download_button(
                label="Download PDF Report",
                data=pdf_bytes,
                file_name=f"evaluation_{eval_id}.pdf",
                mime="application/pdf",
            )

            # Judge overrides
            st.subheader("Judge Overrides")
            if overrides:
                for o in overrides:
                    st.markdown(
                        f"**{o['agent'].title()}**: {o['original_score']} → "
                        f"{o['override_score']} by `{o['overridden_by']}` "
                        f"— _{o['reason']}_"
                    )
            else:
                st.caption("No overrides recorded.")

            # Submit override
            st.subheader("Submit Override")
            with st.form("override"):
                agent = st.selectbox("Agent", ["objective", "code", "ui"])
                original_score = st.number_input("Original Score", 0.0, 10.0, step=0.1)
                override_score = st.number_input("Override Score", 0.0, 10.0, step=0.1)
                reason = st.text_area("Reason (required)")
                if st.form_submit_button("Submit Override"):
                    if not reason.strip():
                        st.error("Reason is required.")
                    else:
                        ov_resp = http.post(
                            f"{API_BASE}/report/{eval_id}/override",
                            json={
                                "agent": agent,
                                "original_score": original_score,
                                "override_score": override_score,
                                "reason": reason,
                            },
                            headers=auth_headers(),
                        )
                        if ov_resp.status_code == 201:
                            st.success("Override recorded.")
                            st.rerun()
                        else:
                            st.error(ov_resp.text)


# ── Evaluation History ────────────────────────────────────────────────────────

elif page == "Evaluation History":
    st.title("Evaluation History")
    col1, col2 = st.columns(2)
    filter_judge = col1.text_input("Filter by judge")
    filter_date = col2.text_input("Filter by date (YYYY-MM-DD)")

    params = {}
    if filter_judge:
        params["judge"] = filter_judge
    if filter_date:
        params["date"] = filter_date

    resp = http.get(f"{API_BASE}/evaluations", params=params, headers=auth_headers())
    if resp.status_code == 200:
        rows = resp.json()
        if not rows:
            st.info("No evaluations found.")
        else:
            for row in rows:
                flags_str = ", ".join(row["flags"]) if row["flags"] else "none"
                with st.expander(
                    f"{row['project_name']} — {row['participant']} "
                    f"| Score: {row['overall_score']} | {row['created_at'][:10]}"
                ):
                    st.markdown(f"**ID:** `{row['evaluation_id']}`")
                    st.markdown(f"**Judge:** {row['triggered_by']}")
                    st.markdown(f"**Flags:** {flags_str}")
                    if st.button("Open Report", key=row["evaluation_id"]):
                        st.session_state.last_eval_id = row["evaluation_id"]
                        st.rerun()
    else:
        st.error(resp.text)


# ── Metrics ───────────────────────────────────────────────────────────────────

elif page == "Metrics":
    st.title("System Metrics")
    resp = http.get(f"{API_BASE}/metrics/summary", headers=auth_headers())
    if resp.status_code == 200:
        m = resp.json()
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Evaluations", m["total_evaluations"])
        col2.metric("Total Overrides", m["total_overrides"])
        col3.metric("Override Rate", f"{m['override_rate']:.1%}")
        col4.metric("Avg Score", m["avg_score"] or "N/A")
        st.caption(
            f"Score range: {m['min_score']} – {m['max_score']}"
            if m["min_score"] is not None else "No evaluations yet."
        )
    else:
        st.error(resp.text)
