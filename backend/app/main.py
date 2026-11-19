import os
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from .database import Base, build_engine, session_factory
from .models import NodeReceipt,Project,Run
from .schemas import ProjectCreate, ProjectRead
from .api.runs import run_router
from .api.simulation import simulation_router
from .api.plan_approvals import plan_approval_router
from .api.delivery import delivery_router
from .api.exports import export_router
from .workflows.runtime import Runtime


def create_app(database_url: str | None = None, checkpoint_path: str | None = None, provider=None) -> FastAPI:
    url = database_url or os.getenv("DATABASE_URL", "sqlite:///./simulator.db")
    engine = build_engine(url)
    sessions = session_factory(engine)

    @asynccontextmanager
    async def lifespan(app):
        # Upgrade verified local schemas before accepting requests.
        try:
            from .migrations import upgrade_database
            upgrade_database(engine)
            yield
        finally:
            runtime.close()
            engine.dispose()

    app = FastAPI(title="Project Management Simulator", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    path = checkpoint_path or (str(Path(engine.url.database).with_suffix('.checkpoints.db')) if engine.url.database not in (None, ':memory:') else ':memory:')
    runtime = Runtime(sessions, path, provider)
    app.include_router(run_router(runtime))
    app.include_router(simulation_router(runtime))
    app.include_router(plan_approval_router(runtime))
    app.include_router(delivery_router(runtime))
    app.include_router(export_router(runtime))
    app.state.runtime = runtime

    @app.get("/api/v1/health")
    def health():
        with sessions() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok", "milestone": "M5", "execution_mode": "simulation"}

    @app.post("/api/v1/projects", response_model=ProjectRead, status_code=201)
    def create_project(payload: ProjectCreate):
        with sessions.begin() as session:
            project = Project(**payload.model_dump())
            session.add(project)
            session.flush()
            result = ProjectRead.model_validate(project)
        return result

    @app.get("/api/v1/projects", response_model=list[ProjectRead])
    def list_projects(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        with sessions() as session:
            return [ProjectRead.model_validate(p) for p in session.scalars(
                select(Project).order_by(Project.created_at, Project.id).offset(offset).limit(limit)
            )]

    @app.get("/api/v1/projects/{project_id}", response_model=ProjectRead)
    def get_project(project_id: str):
        with sessions() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise HTTPException(404, "Project not found")
            return ProjectRead.model_validate(project)

    @app.get('/api/v1/projects/{project_id}/runs')
    def project_runs(project_id: str):
        with sessions() as session:
            if not session.get(Project,project_id):
                raise HTTPException(404,'Project not found')
            runs=session.scalars(select(Run).where(Run.project_id==project_id).order_by(Run.created_at.desc())).all()
            return [{'id':run.id,'status':run.status,'delivery':session.scalar(select(NodeReceipt.id).where(
                NodeReceipt.run_id==run.id,NodeReceipt.node=='delivery_command')) is not None} for run in runs]

    frontend=Path(__file__).resolve().parents[2]/'frontend'/'dist'
    if frontend.is_dir():
        app.mount('/',StaticFiles(directory=frontend,html=True),name='dashboard')

    return app


# Local configuration is optional; exported process settings take precedence.
load_dotenv(Path(__file__).resolve().parents[2] / '.env', override=False)
app = create_app()
