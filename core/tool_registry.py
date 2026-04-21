import importlib.util
from pathlib import Path
from core.config        import ConfigRegistry
from core.sentinel_logger import get_logger


class ToolRegistry:
    """
    Every file in tools/ is a tool.
    Tools are loaded dynamically — the system can write new ones and reload at runtime.

    Tool contract (each tools/*.py must define):
        TOOL_NAME        str
        TOOL_DESCRIPTION str
        TOOL_ENABLED     bool
        TOOL_SCHEMA      dict   — parameter descriptions
        execute(**kwargs) -> str
    """

    def __init__(self, tools_dir: str = "tools", config: ConfigRegistry = None):
        self.tools_dir = Path(tools_dir)
        self.tools_dir.mkdir(exist_ok=True)
        self._tools: dict = {}
        self.config = config
        self.load_all()

    # ── Loading ───────────────────────────────────

    def load_all(self):
        self._tools = {}
        for path in sorted(self.tools_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            self._load_file(path)

    def _load_file(self, path: Path):
        try:
            spec   = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            name = getattr(module, "TOOL_NAME", path.stem)
            self._tools[name] = {
                "module":      module,
                "name":        name,
                "description": getattr(module, "TOOL_DESCRIPTION", "No description"),
                "schema":      getattr(module, "TOOL_SCHEMA", {}),
                "enabled":     getattr(module, "TOOL_ENABLED", True),
                "path":        str(path),
            }
            get_logger().log("DEBUG", "tool_registry", f"Loaded tool: {name}")
        except Exception as e:
            get_logger().log("ERROR", "tool_registry", f"Failed to load {path.name}", {
                "path": str(path), "error": str(e),
            })

    # ── Queries ───────────────────────────────────

    def get_tool_descriptions(self) -> list:
        return [
            {
                "name":        t["name"],
                "description": t["description"],
                "schema":      t["schema"],
                "enabled":     t["enabled"],
            }
            for t in self._tools.values()
        ]

    def get_all_tools(self) -> dict:
        return self._tools

    def get_tool_code(self, name: str) -> str:
        if name not in self._tools:
            return ""
        return Path(self._tools[name]["path"]).read_text(encoding="utf-8")

    # ── Execution ─────────────────────────────────

    def _get_max_output(self) -> int:
        if self.config:
            return self.config.get("MAX_TOOL_OUTPUT")
        return 16000

    def execute(self, name: str, args: dict) -> str:
        if name not in self._tools:
            return f"Error: tool '{name}' not found"
        tool = self._tools[name]
        if not tool["enabled"]:
            return f"Error: tool '{name}' is disabled"
        try:
            result = str(tool["module"].execute(**args))

            # Cap output to prevent context window overflow
            max_out = self._get_max_output()
            if len(result) > max_out:
                total_len = len(result)
                result = (
                    result[:max_out]
                    + f"\n\n[OUTPUT TRUNCATED — {total_len} total chars, showing first {max_out}. "
                    f"Use 'filesystem' read with a specific path for full content.]"
                )
                get_logger().log("WARNING", "tool_registry", f"Output truncated for {name}", {
                    "tool": name, "total_chars": total_len, "cap": max_out,
                })

            return result
        except Exception as e:
            get_logger().log("ERROR", "tool_registry", f"Execution error in {name}", {
                "tool": name, "error": str(e),
            })
            return f"Error in {name}: {e}"

    # ── Mutations ─────────────────────────────────

    def set_enabled(self, name: str, enabled: bool):
        if name in self._tools:
            self._tools[name]["enabled"] = enabled

    def save_tool_code(self, name: str, code: str):
        if name not in self._tools:
            return
        path = Path(self._tools[name]["path"])
        path.write_text(code, encoding="utf-8")
        self._load_file(path)

    def create_tool(self, name: str, code: str):
        path = self.tools_dir / f"{name}.py"
        path.write_text(code, encoding="utf-8")
        self._load_file(path)
