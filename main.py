import asyncio
import json
import os
import re
import shutil

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


def _find_opencode_cli() -> str | None:
    """查找 OpenCode CLI 路径"""
    env_path = os.environ.get("OPENCODE_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    npm_exe_new = os.path.expanduser(
        r"~\AppData\Roaming\npm\node_modules\opencode-ai\node_modules\opencode-windows-x64\bin\opencode.exe"
    )
    if os.path.exists(npm_exe_new):
        return npm_exe_new

    npm_exe_old = os.path.expanduser(
        r"~\AppData\Roaming\npm\node_modules\opencode-ai\bin\opencode.exe"
    )
    if os.path.exists(npm_exe_old):
        return npm_exe_old

    which_path = shutil.which("opencode")
    if which_path:
        if which_path.lower().endswith(".cmd"):
            return "opencode"
        return which_path

    return None


def _strip_ansi(text: str) -> str:
    """移除 ANSI 颜色码"""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


@register(
    "astrbot_plugin_opencode_tool",
    "opencode",
    "让 AstrBot 的 Agent 能够主动调用 OpenCode 执行开发任务",
    "2.2.0",
    "支持 Plan/Build 模式、dry_run 预览",
)
class OpenCodeToolPlugin(Star):
    """OpenCode 工具插件 - 使用 CLI attach 模式"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._opencode_cli = _find_opencode_cli()
        self._server_port = config.get("server_port", 9501)
        self._timeout = config.get("timeout", 300)
        self._server_url = f"http://localhost:{self._server_port}"
        self._server_process = None

        if self._opencode_cli:
            logger.info(f"[OpenCode工具] 插件已加载，CLI: {self._opencode_cli}")
        else:
            logger.warning("[OpenCode工具] 插件已加载，但未找到 OpenCode CLI")

    async def _ensure_server(self) -> bool:
        """确保服务器运行"""
        # 检查端口是否被占用
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('localhost', self._server_port))
            sock.close()
            if result == 0:
                logger.info(f"[OpenCode工具] 端口 {self._server_port} 已被占用，假设服务器已运行")
                return True
        except Exception:
            pass

        # 启动服务器
        if not self._opencode_cli:
            return False

        logger.info("[OpenCode工具] 启动 OpenCode 服务器...")
        self._server_process = await asyncio.create_subprocess_exec(
            self._opencode_cli,
            "serve",
            "--port", str(self._server_port),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.expanduser("~"),
        )

        # 等待服务器启动
        for _ in range(15):
            await asyncio.sleep(1)
            if self._server_process.returncode is not None:
                logger.error("[OpenCode工具] 服务器启动失败")
                return False
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = sock.connect_ex(('localhost', self._server_port))
                sock.close()
                if result == 0:
                    logger.info("[OpenCode工具] 服务器启动成功")
                    return True
            except Exception:
                pass

        logger.warning("[OpenCode工具] 服务器启动超时")
        return False

    async def _run_with_attach(self, task: str) -> tuple[str, str]:
        """通过 attach 模式执行任务"""
        args = [
            self._opencode_cli,
            "run",
            "--attach", self._server_url,
            "--format", "json",
            task,
        ]

        logger.info(f"[OpenCode工具] 执行: opencode run --attach ...")

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.expanduser("~"),
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return "", "任务执行超时"

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        return stdout_text, _strip_ansi(stderr_text)

    def _parse_json_output(self, stdout_text: str) -> str | None:
        """解析 JSON 输出"""
        if not stdout_text.strip():
            return None

        texts = []
        for line in stdout_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                if event_type == "message":
                    role = event.get("role", "")
                    content = event.get("content", "")
                    if role == "assistant" and content:
                        texts.append(content)

                if event_type == "text":
                    text = event.get("text", "")
                    if text:
                        texts.append(text)

                if event_type == "result":
                    result = event.get("result", "")
                    if result:
                        texts.append(result)

            except json.JSONDecodeError:
                continue

        return "\n".join(texts) if texts else None

    @filter.llm_tool(name="opencode_execute")
    async def opencode_execute(
        self, event: AstrMessageEvent, task: str,
        mode: str = "build", dry_run: bool = False
    ) -> str:
        """调用 OpenCode 执行开发任务，如读写文件、代码重构、生成单元测试等。

        使用场景：
        - 用户要求读取或修改代码文件
        - 用户要求重构代码
        - 用户要求生成单元测试
        - 用户要求分析代码结构
        - 任何需要操作代码库的任务

        工作流程（推荐）：
        1. 先用 mode="plan" 让 OpenCode 分析任务并制定计划
        2. 向用户展示计划，询问是否确认执行
        3. 用户确认后，用 mode="build" 实际执行

        Args:
            task(string): 要执行的任务描述，详细说明需要 OpenCode 做什么
            mode(string): 执行模式。"plan"=仅分析制定计划不修改文件，"build"=实际执行修改。默认 "build"
            dry_run(boolean): 是否仅预览工具调用而不实际执行。默认 false
        """
        logger.info(f"[OpenCode工具] 被调用: task={task[:50]}..., mode={mode}, dry_run={dry_run}")

        if not self._opencode_cli:
            return (
                "❌ 未找到 OpenCode CLI 程序。\n\n"
                "请先安装：npm install -g opencode-ai\n"
                "或设置环境变量 OPENCODE_PATH"
            )

        if dry_run:
            mode_label = "📋 计划模式 (Plan)" if mode == "plan" else "🔨 构建模式 (Build)"
            return (
                f"📋 **OpenCode 任务预览**\n\n"
                f"**任务内容：**\n{task}\n\n"
                f"**执行模式：** {mode_label}\n\n"
                f"**执行方式：** OpenCode CLI (serve + attach)\n\n"
                f"**配置：**\n"
                f"• 端口: {self._server_port}\n"
                f"• 超时: {self._timeout}秒\n\n"
                f"---\n"
                f"✅ 确认执行请回复「确认执行」\n"
                f"❌ 取消请回复「取消」"
            )

        try:
            if not await self._ensure_server():
                return "❌ OpenCode 服务器启动失败"

            if mode == "plan":
                prompt = (
                    f"[PLAN MODE - 仅分析，不修改文件]\n\n"
                    f"请分析以下任务，制定详细的执行计划：\n\n"
                    f"{task}\n\n"
                    f"要求：\n"
                    f"1. 分析当前代码结构\n"
                    f"2. 列出需要修改的文件\n"
                    f"3. 说明每个文件的修改内容\n"
                    f"4. 注意事项和潜在风险\n"
                    f"5. 不要实际修改任何文件"
                )
            else:
                prompt = task

            stdout_text, stderr_text = await self._run_with_attach(prompt)

            # 检查错误
            if stderr_text.strip():
                if "session not found" not in stderr_text.lower():
                    logger.error(f"[OpenCode工具] 执行失败: {stderr_text[:200]}")
                    return f"❌ OpenCode 执行失败：\n{stderr_text[:500]}"

            # 解析输出
            result = self._parse_json_output(stdout_text)

            if result:
                display = result[:2000]
                if len(result) > 2000:
                    display += "\n\n... (输出已截断)"
                return f"✅ OpenCode 任务完成：\n\n{display}"

            if stdout_text.strip():
                display = stdout_text.strip()[:2000]
                return f"✅ OpenCode 任务完成：\n\n{display}"

            return "⚠️ OpenCode 执行完成，但没有输出内容"

        except TimeoutError:
            return "⏰ OpenCode 任务执行超时"
        except Exception as e:
            logger.error(f"[OpenCode工具] 调用异常: {e}")
            return f"❌ 调用 OpenCode 失败：{str(e)}"

    async def terminate(self):
        """插件卸载"""
        if self._server_process and self._server_process.returncode is None:
            try:
                self._server_process.kill()
            except Exception:
                pass
        logger.info("[OpenCode工具] 插件已卸载")
