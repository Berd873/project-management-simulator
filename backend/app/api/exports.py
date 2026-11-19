from datetime import date,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,HTTPException,Query,Response
from sqlalchemy import select
from ..models import Baseline,Project,Run
from ..services.planning import Plan
from ..services.project_export import export_project_xml


def export_router(runtime):
    router=APIRouter(prefix='/api/v1/runs')
    @router.get('/{run_id}/export')
    def export(run_id: str,format: Literal['ms-project-xml']='ms-project-xml',
               baseline_version: int | None=Query(None,ge=1),start_date: date | None=None):
        with runtime.sessions() as session:
            run=session.get(Run,run_id)
            if not run:
                raise HTTPException(404,'Run not found')
            statement=select(Baseline).where(Baseline.project_id==run.project_id)
            if baseline_version is not None:
                statement=statement.where(Baseline.version==baseline_version)
            baseline=session.scalar(statement.order_by(Baseline.version.desc()).limit(1))
            if not baseline:
                raise HTTPException(404,'Approved baseline not found')
            project=session.get(Project,run.project_id)
            created=project.created_at
            if created.tzinfo is None:
                created=created.replace(tzinfo=timezone.utc)
            day=start_date or created.astimezone(timezone(timedelta(hours=8))).date()
            try:
                data=export_project_xml(Plan.model_validate(baseline.content['plan']),project.name,day,project.id)
            except (ValueError,OverflowError) as exc:
                raise HTTPException(422,str(exc)) from exc
            return Response(data,media_type='application/xml',headers={
                'Content-Disposition':f'attachment; filename="simulation-plan-v{baseline.version}.xml"',
                'X-Execution-Mode':'simulation','X-Baseline-Version':str(baseline.version)})
    return router
