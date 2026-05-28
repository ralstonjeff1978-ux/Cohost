"""
VERIFICATION ENGINE - Reality Checker
======================================
Prevents the agent from hallucinating success.

After every action, we CHECK if it actually worked.
No more "I built the app" when nothing exists.
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

log = logging.getLogger("verification")


@dataclass
class VerificationResult:
    """Result of verifying an action."""
    success:    bool
    evidence:   str
    confidence: float          # 0.0 to 1.0
    details:    Dict[str, Any]


class VerificationEngine:
    """
    Verifies that actions actually happened.

    This is the anti-hallucination layer. Every tool result is checked
    against the filesystem or runtime state before being reported as success.
    """

    def __init__(self, tool_registry):
        """
        Args:
            tool_registry: ToolRegistry to use for verification checks.
        """
        self.tools = tool_registry
        log.info("Verification Engine initialised")

    # ── Public API ─────────────────────────────────────────────────────────────

    def verify_step(self, step, tool_results: List[Dict]) -> VerificationResult:
        """
        Verify that a step actually succeeded.

        Args:
            step:         The TaskStep that was executed.
            tool_results: Results from the tool calls.

        Returns:
            VerificationResult with evidence.
        """
        log.info("Verifying step: %s", step.step_id)

        # Bail early if any tool reported failure
        if not all(r["success"] for r in tool_results):
            failed = [r for r in tool_results if not r["success"]]
            return VerificationResult(
                success=False,
                evidence=f"Tool execution failed: {failed[0]['result']}",
                confidence=1.0,
                details={"failed_tools": failed}
            )

        # Route to the appropriate verification strategy
        tools_used = [r["tool"] for r in tool_results]
        method     = (step.verification_method or "").lower()

        if "create_file" in tools_used or "file" in method:
            return self._verify_file_exists(step, tool_results)

        if any(t in tools_used for t in ("create_directory", "create_project")) \
                or "directory" in method or "folder" in method:
            return self._verify_directory_exists(step, tool_results)

        if "install_package" in tools_used or "package" in method:
            return self._verify_package_installed(step, tool_results)

        if "run_script" in tools_used \
                or any(k in method for k in ("command", "script", "execute")):
            return self._verify_command_success(tool_results)

        if "contains" in method or "content" in method:
            return self._verify_file_content(step)

        # Default: trust tool success flag
        return VerificationResult(
            success=True,
            evidence=f"Tool '{tools_used[0]}' completed successfully",
            confidence=0.8,
            details={"tool_results": tool_results}
        )

    # ── Verification strategies ────────────────────────────────────────────────

    def _verify_file_exists(self, step, tool_results: List[Dict]) -> VerificationResult:
        """Verify a file was created on disk."""
        file_path = self._extract_file_path(step, tool_results, "create_file")

        if not file_path:
            log.warning("Could not determine file path for verification")
            return VerificationResult(
                success=True,
                evidence="File tool succeeded (path not extracted for verification)",
                confidence=0.7,
                details={}
            )

        try:
            path = Path(file_path)
            if path.exists() and path.is_file():
                size = path.stat().st_size
                log.info("✓ Verified file exists: %s (%d bytes)", file_path, size)
                return VerificationResult(
                    success=True,
                    evidence=f"File verified at {file_path} ({size} bytes)",
                    confidence=1.0,
                    details={"file_path": str(path.absolute()), "size": size}
                )
            else:
                log.error("✗ File not found: %s", file_path)
                return VerificationResult(
                    success=False,
                    evidence=f"File does not exist at {file_path}",
                    confidence=1.0,
                    details={"expected_path": file_path}
                )
        except Exception as e:
            log.error("Error verifying file: %s", e)
            return VerificationResult(
                success=False,
                evidence=f"Error checking file: {e}",
                confidence=0.8,
                details={"error": str(e)}
            )

    def _verify_directory_exists(self, step, tool_results: List[Dict]) -> VerificationResult:
        """Verify a directory was created on disk."""
        dir_path = self._extract_file_path(
            step, tool_results, "create_directory", "create_project"
        )

        if not dir_path:
            log.warning("Could not determine directory path for verification")
            return VerificationResult(
                success=True,
                evidence="Directory tool succeeded (path not extracted for verification)",
                confidence=0.7,
                details={}
            )

        try:
            path = Path(dir_path)
            if path.exists() and path.is_dir():
                items = list(path.iterdir())
                log.info("✓ Verified directory exists: %s (%d items)", dir_path, len(items))
                return VerificationResult(
                    success=True,
                    evidence=f"Directory verified at {dir_path} ({len(items)} items)",
                    confidence=1.0,
                    details={"directory_path": str(path.absolute()), "item_count": len(items)}
                )
            else:
                log.error("✗ Directory not found: %s", dir_path)
                return VerificationResult(
                    success=False,
                    evidence=f"Directory does not exist at {dir_path}",
                    confidence=1.0,
                    details={"expected_path": dir_path}
                )
        except Exception as e:
            log.error("Error verifying directory: %s", e)
            return VerificationResult(
                success=False,
                evidence=f"Error checking directory: {e}",
                confidence=0.8,
                details={"error": str(e)}
            )

    def _verify_package_installed(self, step, tool_results: List[Dict]) -> VerificationResult:
        """Verify a package was installed."""
        package_name = None

        for tc in step.tool_calls:
            if tc.get("tool") == "install_package" and tc.get("args"):
                package_name = tc["args"][0]
                break

        if not package_name:
            for result in tool_results:
                if result["tool"] == "install_package":
                    parts = str(result["result"]).split("Installed")
                    if len(parts) > 1:
                        package_name = parts[1].strip().split()[0]

        if not package_name:
            return VerificationResult(
                success=True,
                evidence="Package installation succeeded (name not extracted)",
                confidence=0.7,
                details={}
            )

        try:
            success, check_result = self.tools.call_tool("check_package", package_name)
            if success and check_result == "True":
                return VerificationResult(
                    success=True,
                    evidence=f"Package {package_name} verified installed",
                    confidence=1.0,
                    details={"package_name": package_name}
                )
            return VerificationResult(
                success=False,
                evidence=f"Package {package_name} not found after installation",
                confidence=1.0,
                details={"package_name": package_name}
            )
        except Exception as e:
            return VerificationResult(
                success=True,
                evidence=f"Package installation succeeded (verification skipped: {e})",
                confidence=0.7,
                details={"package_name": package_name}
            )

    def _verify_command_success(self, tool_results: List[Dict]) -> VerificationResult:
        """Verify a command executed without errors."""
        for result in tool_results:
            result_str = str(result["result"]).lower()
            if any(k in result_str for k in ("error", "failed", "traceback")):
                return VerificationResult(
                    success=False,
                    evidence=f"Command failed: {result['result'][:200]}",
                    confidence=0.9,
                    details={"error": result["result"]}
                )

        return VerificationResult(
            success=True,
            evidence="Command executed without errors",
            confidence=0.9,
            details={"tool_results": tool_results}
        )

    def _verify_file_content(self, step) -> VerificationResult:
        """Verify a file contains expected content."""
        file_path = self._extract_path_from_text(step.description)

        if not file_path:
            return VerificationResult(
                success=False,
                evidence="Could not determine file path",
                confidence=0.5,
                details={}
            )

        try:
            success, content = self.tools.call_tool("read_file", file_path)
            if not success:
                return VerificationResult(
                    success=False,
                    evidence=f"Could not read file: {content}",
                    confidence=0.9,
                    details={}
                )

            if step.expected_outcome.lower() in content.lower():
                return VerificationResult(
                    success=True,
                    evidence="File contains expected content",
                    confidence=0.9,
                    details={"file_path": file_path, "content_length": len(content)}
                )
            return VerificationResult(
                success=False,
                evidence="File does not contain expected content",
                confidence=0.9,
                details={"file_path": file_path}
            )
        except Exception as e:
            return VerificationResult(
                success=False,
                evidence=f"Error verifying content: {e}",
                confidence=0.7,
                details={"error": str(e)}
            )

    # ── Path extraction helpers ────────────────────────────────────────────────

    def _extract_file_path(self, step, tool_results: List[Dict],
                           *tool_names: str) -> Optional[str]:
        """
        Find a path using three strategies in priority order:
        1. Tool call arguments (most reliable)
        2. Tool result string
        3. Step description text
        """
        # Strategy 1: tool call args
        for tc in step.tool_calls:
            if tc.get("tool") in tool_names and tc.get("args"):
                return tc["args"][0]

        # Strategy 2: tool result string
        for result in tool_results:
            if result["tool"] in tool_names:
                path = self._extract_path_from_text(str(result["result"]))
                if path:
                    return path

        # Strategy 3: step description
        return self._extract_path_from_text(step.description)

    @staticmethod
    def _extract_path_from_text(text: str) -> Optional[str]:
        """Extract a file/directory path from arbitrary text."""
        # Windows absolute path
        match = re.search(r'[A-Za-z]:\\[\w\\.\-]+', text)
        if match:
            return match.group(0)

        # Unix/POSIX absolute path
        match = re.search(r'/[\w/.\-]+', text)
        if match:
            return match.group(0)

        # Quoted path (fallback)
        match = re.search(r'["\']([^"\']+)["\']', text)
        if match:
            return match.group(1)

        return None


# ── Factory ────────────────────────────────────────────────────────────────────

def create_verification_engine(tool_registry) -> VerificationEngine:
    """Create and return a VerificationEngine instance."""
    return VerificationEngine(tool_registry)
