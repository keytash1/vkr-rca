"""Load a small explicitly approved, project-scoped local guidance corpus."""

import copy
import hashlib
import json
from pathlib import Path
import re
import stat

from assistant_tools import SnapshotTools, ToolError


class RunbookCorpus:
    def __init__(self, path):
        path = Path(path)
        if (
            path.is_symlink()
            or not stat.S_ISREG(path.stat().st_mode)
            or path.stat().st_size > 128 * 1024
        ):
            raise ToolError("RUNBOOK_CORPUS_FILE_INVALID")
        data = path.read_bytes()
        if len(data) > 128 * 1024:
            raise ToolError("RUNBOOK_CORPUS_FILE_INVALID")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ToolError("RUNBOOK_DUPLICATE_FIELD")
                result[key] = value
            return result

        try:
            source = json.loads(data, object_pairs_hook=pairs)
        except (ValueError, RecursionError, UnicodeError):
            raise ToolError("RUNBOOK_CORPUS_JSON_INVALID") from None
        if (
            not isinstance(source, dict)
            or set(source)
            != {
                "schema_version",
                "version",
                "external_transmission_approved",
                "projects",
                "entries",
            }
            or source["schema_version"] != "runbooks-v1"
            or source["external_transmission_approved"] is not True
            or not isinstance(source["version"], str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", source["version"])
            or not isinstance(source["projects"], list)
            or not 1 <= len(source["projects"]) <= 100
            or any(
                not isinstance(p, str) or not re.fullmatch(r"[a-z0-9_-]{1,128}", p)
                for p in source["projects"]
            )
            or len(set(source["projects"])) != len(source["projects"])
        ):
            raise ToolError("RUNBOOK_CORPUS_NOT_APPROVED")
        self.entries = SnapshotTools._validate_runbooks(source["entries"])
        self.projects = frozenset(source["projects"])
        self.version = source["version"]
        self.sha256 = hashlib.sha256(data).hexdigest()

    def for_project(self, project):
        return copy.deepcopy(self.entries) if project in self.projects else []
