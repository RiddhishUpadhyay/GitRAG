import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set
from tree_sitter import Language, Parser
import tree_sitter_python
import tree_sitter_javascript

logger = logging.getLogger(__name__)

@dataclass
class CodeChunk:
    content: str
    file_path: str  # relative path
    start_line: int # 1-based, inclusive
    end_line: int   # 1-based, inclusive
    chunk_type: str # "function", "class", "module", "fallback"
    chunk_id: str   # MD5 hash of content + file_path

    def __post_init__(self):
        if not self.chunk_id:
            hasher = hashlib.md5()
            hasher.update(f"{self.file_path}:{self.start_line}:{self.end_line}".encode("utf-8"))
            hasher.update(self.content.encode("utf-8"))
            self.chunk_id = hasher.hexdigest()

def get_language_from_extension(file_extension: str) -> str | None:
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx"
    }
    return ext_map.get(file_extension.lower())

def split_large_text(text: str, max_lines: int = 60, overlap_lines: int = 10) -> List[tuple[str, int, int]]:
    """Splits a large text block into smaller overlapping sub-blocks."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return [(text, 0, len(lines))]

    chunks = []
    start = 0
    while start < len(lines):
        end = min(start + max_lines, len(lines))
        chunk_content = "\n".join(lines[start:end])
        chunks.append((chunk_content, start, end))
        if end == len(lines):
            break
        start += (max_lines - overlap_lines)
    return chunks

def chunk_file(file_path: Path, repo_path: Path) -> List[CodeChunk]:
    """
    Chunks a single file using tree-sitter AST parsing if supported,
    or a sliding window fallback if not supported.
    """
    relative_path = str(file_path.relative_to(repo_path)).replace("\\", "/")
    
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return []

    if not code.strip():
        return []

    lines = code.splitlines()
    num_lines = len(lines)
    
    lang = get_language_from_extension(file_path.suffix)
    if not lang:
        return chunk_fallback(code, relative_path)

    try:
        if lang == "python":
            parser = Parser(Language(tree_sitter_python.language()))
        elif lang in ("javascript", "typescript", "tsx"):
            parser = Parser(Language(tree_sitter_javascript.language()))
        else:
            return chunk_fallback(code, relative_path)

        tree = parser.parse(bytes(code, "utf-8"))
    except Exception as e:
        logger.warning(f"Tree-sitter parser failed for {relative_path} ({lang}), falling back: {e}")
        return chunk_fallback(code, relative_path)

    # Walk the tree and collect interesting nodes (functions, classes, methods)
    # Target node types based on language
    target_types = {
        "python": {"function_definition", "class_definition"},
        "javascript": {"function_declaration", "class_declaration", "method_definition", "arrow_function"},
        "typescript": {"function_declaration", "class_declaration", "method_definition", "arrow_function"},
        "tsx": {"function_declaration", "class_declaration", "method_definition", "arrow_function"}
    }.get(lang, set())

    # We want to identify the byte/line ranges of class/function nodes
    chunk_nodes = []
    
    def traverse(node):
        if node.type in target_types:
            chunk_nodes.append(node)
            # If it's a function or method, don't descend further to avoid nested function issues
            if "function" in node.type or "method" in node.type:
                return
        for child in node.children:
            traverse(child)

    traverse(tree.root_node)

    # Track which lines are covered by our AST chunks (0-indexed)
    covered_lines: Set[int] = set()
    chunks: List[CodeChunk] = []

    # Process AST nodes
    for node in chunk_nodes:
        start_line = node.start_point[0]
        end_line = node.end_point[0]  # inclusive end line index
        
        # Extract text for the node
        node_lines = lines[start_line:end_line + 1]
        node_content = "\n".join(node_lines)
        
        chunk_type = "class" if "class" in node.type else "function"
        
        # Check if node is too large, split it if necessary
        if len(node_lines) > 80:
            sub_chunks = split_large_text(node_content, max_lines=60, overlap_lines=10)
            for sub_text, sub_start, sub_end in sub_chunks:
                chunks.append(
                    CodeChunk(
                        content=sub_text,
                        file_path=relative_path,
                        start_line=start_line + sub_start + 1,
                        end_line=start_line + sub_end,
                        chunk_type=f"{chunk_type}_split",
                        chunk_id=""
                    )
                )
        else:
            chunks.append(
                CodeChunk(
                    content=node_content,
                    file_path=relative_path,
                    start_line=start_line + 1,
                    end_line=end_line + 1,
                    chunk_type=chunk_type,
                    chunk_id=""
                )
            )
            
        for line_num in range(start_line, end_line + 1):
            covered_lines.add(line_num)

    # Process remaining uncovered lines (module scope, global variables, imports)
    uncovered_start = None
    for i in range(num_lines):
        if i not in covered_lines:
            if uncovered_start is None:
                uncovered_start = i
        else:
            if uncovered_start is not None:
                # We hit a covered line, flush the previous uncovered block
                flush_uncovered_block(lines, uncovered_start, i, relative_path, chunks)
                uncovered_start = None
                
    if uncovered_start is not None:
        flush_uncovered_block(lines, uncovered_start, num_lines, relative_path, chunks)

    return chunks

def flush_uncovered_block(lines: List[str], start: int, end: int, file_path: str, chunks: List[CodeChunk]):
    """Groups a block of lines into module-level chunks."""
    block_text = "\n".join(lines[start:end])
    if not block_text.strip():
        return
        
    if (end - start) > 60:
        sub_chunks = split_large_text(block_text, max_lines=50, overlap_lines=10)
        for sub_text, sub_start, sub_end in sub_chunks:
            chunks.append(
                CodeChunk(
                    content=sub_text,
                    file_path=file_path,
                    start_line=start + sub_start + 1,
                    end_line=start + sub_end,
                    chunk_type="module_split",
                    chunk_id=""
                )
            )
    else:
        chunks.append(
            CodeChunk(
                content=block_text,
                file_path=file_path,
                start_line=start + 1,
                end_line=end,
                chunk_type="module",
                chunk_id=""
            )
        )

def chunk_fallback(code: str, file_path: str) -> List[CodeChunk]:
    """Fallback chunker using a sliding window for unsupported files."""
    lines = code.splitlines()
    sub_chunks = split_large_text(code, max_lines=50, overlap_lines=10)
    chunks = []
    for sub_text, start, end in sub_chunks:
        chunks.append(
            CodeChunk(
                content=sub_text,
                file_path=file_path,
                start_line=start + 1,
                end_line=end,
                chunk_type="fallback",
                chunk_id=""
            )
        )
    return chunks
