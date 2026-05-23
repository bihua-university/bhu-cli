from collections.abc import Callable
from pathlib import Path
from typing import override

from kaos.path import KaosPath
from kosong.tooling import CallableTool2, ToolError, ToolReturnValue
from pydantic import BaseModel, Field

from kimi_cli.soul.agent import Runtime
from kimi_cli.soul.approval import Approval
from kimi_cli.tools.display import DisplayBlock
from kimi_cli.tools.file import FileActions
from kimi_cli.tools.file.plan_mode import inspect_plan_edit_target
from kimi_cli.tools.utils import load_desc
from kimi_cli.utils.diff import build_diff_blocks
from kimi_cli.utils.logging import logger
from kimi_cli.utils.path import is_within_workspace, kaos_path_from_user_input

_BASE_DESCRIPTION = load_desc(Path(__file__).parent / "edit.md")


class Params(BaseModel):
    path: str = Field(
        description=(
            "The path to the file to edit. Absolute paths are required when editing files "
            "outside the working directory."
        )
    )
    start: int = Field(
        description="The starting line number to delete (1-based, inclusive).",
        ge=1,
    )
    end: int = Field(
        description="The ending line number to delete (1-based, exclusive).",
        ge=1,
    )
    new_string: str = Field(
        description="The new string to insert at the start line position after deletion.",
    )


class EditFile(CallableTool2[Params]):
    name: str = "EditFile"
    description: str = _BASE_DESCRIPTION
    params: type[Params] = Params

    def __init__(self, runtime: Runtime, approval: Approval):
        super().__init__()
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR
        self._additional_dirs = runtime.additional_dirs
        self._approval = approval
        self._plan_mode_checker: Callable[[], bool] | None = None
        self._plan_file_path_getter: Callable[[], Path | None] | None = None

    def bind_plan_mode(
        self, checker: Callable[[], bool], path_getter: Callable[[], Path | None]
    ) -> None:
        """Bind plan mode state checker and plan file path getter."""
        self._plan_mode_checker = checker
        self._plan_file_path_getter = path_getter

    async def _validate_path(self, path: KaosPath) -> ToolError | None:
        """Validate that the path is safe to edit."""
        resolved_path = path.canonical()

        if (
            not is_within_workspace(resolved_path, self._work_dir, self._additional_dirs)
            and not path.is_absolute()
        ):
            return ToolError(
                message=(
                    f"`{path}` is not an absolute path. "
                    "You must provide an absolute path to edit a file "
                    "outside the working directory."
                ),
                brief="Invalid path",
            )
        return None

    @override
    async def __call__(self, params: Params) -> ToolReturnValue:
        if not params.path:
            return ToolError(
                message="File path cannot be empty.",
                brief="Empty file path",
            )

        if params.start > params.end:
            return ToolError(
                message=(
                    f"Start line ({params.start}) must not be greater than end line ({params.end})."
                ),
                brief="Invalid line range",
            )

        try:
            p = kaos_path_from_user_input(params.path)
            if err := await self._validate_path(p):
                return err
            p = p.canonical()

            plan_target = inspect_plan_edit_target(
                p,
                plan_mode_checker=self._plan_mode_checker,
                plan_file_path_getter=self._plan_file_path_getter,
            )
            if isinstance(plan_target, ToolError):
                return plan_target

            is_plan_file_edit = plan_target.is_plan_target

            if not await p.exists():
                if is_plan_file_edit:
                    return ToolError(
                        message=(
                            "The current plan file does not exist yet. "
                            "Use WriteFile to create it before calling EditFile."
                        ),
                        brief="Plan file not created",
                    )
                return ToolError(
                    message=f"`{params.path}` does not exist.",
                    brief="File not found",
                )
            if not await p.is_file():
                return ToolError(
                    message=f"`{params.path}` is not a file.",
                    brief="Invalid path",
                )

            # Read the file content
            content = await p.read_text(errors="replace")
            original_content = content

            lines = content.splitlines()
            total_lines = len(lines)

            if params.start > total_lines:
                return ToolError(
                    message=(
                        f"Start line ({params.start}) exceeds total line count ({total_lines})."
                    ),
                    brief="Line out of range",
                )

            # Determine if original file ends with a trailing newline
            has_trailing_newline = content.endswith("\n") or content.endswith("\r\n")

            # end is exclusive, so it can be total_lines + 1 (delete to end)
            end = min(params.end, total_lines + 1)

            # Build new content: lines before start, new_string, lines after end-1
            new_lines = (
                lines[: params.start - 1] + params.new_string.splitlines() + lines[end - 1 :]
            )
            new_content = "\n".join(new_lines)
            if has_trailing_newline:
                new_content += "\n"

            # Check if any changes were made
            if new_content == original_content:
                return ToolError(
                    message="No changes were made. The new content is identical to the original.",
                    brief="No changes made",
                )

            diff_blocks: list[DisplayBlock] = await build_diff_blocks(
                str(p), original_content, new_content
            )

            action = (
                FileActions.EDIT
                if is_within_workspace(p, self._work_dir, self._additional_dirs)
                else FileActions.EDIT_OUTSIDE
            )

            # Plan file edits are auto-approved; all other edits need approval.
            if not is_plan_file_edit:
                result = await self._approval.request(
                    self.name,
                    action,
                    f"Edit file `{p}`",
                    display=diff_blocks,
                )
                if not result:
                    return result.rejection_error()

            # Write the modified content back to the file
            await p.write_text(new_content, errors="replace")

            deleted_count = end - params.start
            inserted_count = len(params.new_string.splitlines())
            return ToolReturnValue(
                is_error=False,
                output="",
                message=(
                    f"File successfully edited. "
                    f"Deleted {deleted_count} line(s), inserted {inserted_count} line(s)."
                ),
                display=diff_blocks,
            )

        except Exception as e:
            logger.warning("EditFile failed: {path}: {error}", path=params.path, error=e)
            return ToolError(
                message=f"Failed to edit. Error: {e}",
                brief="Failed to edit file",
            )
