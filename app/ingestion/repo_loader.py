import os
import shutil
import hashlib
import logging
import stat
from pathlib import Path
from typing import List, Tuple
import git
import pathspec

from app.config import settings

logger = logging.getLogger(__name__)

# System directories and files to ignore globally even if not in .gitignore
GLOBAL_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv", "env", ".env",
    "dist", "build", "target", "bin", "obj", ".idea", ".vscode", ".pytest_cache"
}

GLOBAL_IGNORE_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", 
    "Gemfile.lock", "composer.lock", "cargo.lock"
}

def get_repo_id(repo_url: str) -> str:
    """Generate a stable, unique ID for a repository URL."""
    return hashlib.md5(repo_url.strip().encode("utf-8")).hexdigest()

def force_rmtree(path: Path):
    """Deletes a directory tree on Windows, forcing removal of read-only files."""
    if not path.exists():
        return
    
    def remove_readonly(func, p, excinfo):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        shutil.rmtree(path, onerror=remove_readonly)
    except Exception:
        shutil.rmtree(path, ignore_errors=True)

def clean_repo_temp_dir(repo_url: str):
    """Deletes the cloned directory for a repo if it exists."""
    repo_id = get_repo_id(repo_url)
    clone_path = Path(settings.TEMP_DIR) / repo_id
    if clone_path.exists():
        force_rmtree(clone_path)

def clone_repo(repo_url: str) -> Path:
    """Clones a GitHub repository to the temporary directory with depth=1."""
    repo_id = get_repo_id(repo_url)
    clone_path = Path(settings.TEMP_DIR) / repo_id
    
    # If the directory already exists, clear it first
    if clone_path.exists():
        logger.info(f"Directory {clone_path} exists. Cleaning up.")
        force_rmtree(clone_path)
        
    logger.info(f"Cloning {repo_url} into {clone_path}...")
    try:
        git.Repo.clone_from(repo_url, clone_path, depth=1)
    except Exception as e:
        logger.error(f"Failed to clone repository {repo_url}: {e}")
        raise ValueError(f"Failed to clone repository: {e}")
        
    return clone_path

def is_binary(file_path: Path) -> bool:
    """Checks if a file is binary by scanning for null bytes."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                return True
        return False
    except Exception:
        # If we can't open/read, treat as binary/unreadable
        return True

def load_gitignore(repo_path: Path) -> pathspec.PathSpec:
    """Loads .gitignore patterns and returns a PathSpec object."""
    gitignore_path = repo_path / ".gitignore"
    patterns = []
    if gitignore_path.exists():
        try:
            with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                patterns = f.read().splitlines()
        except Exception as e:
            logger.warning(f"Failed to read .gitignore: {e}")
            
    # Add a fallback empty pathspec if no .gitignore or error
    return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, patterns)

def load_and_filter_repo(repo_path: Path) -> Tuple[List[Path], int]:
    """
    Walks repository path, filters files, checks size.
    Returns:
        List[Path]: List of valid, non-ignored file paths.
        int: Total size in bytes.
    """
    spec = load_gitignore(repo_path)
    valid_files = []
    total_size = 0
    
    for root, dirs, files in os.walk(repo_path):
        # In-place modify dirs to skip global ignore directories
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        
        for file in files:
            file_path = Path(root) / file
            relative_path = file_path.relative_to(repo_path)
            
            # Check global ignores
            if file in GLOBAL_IGNORE_FILES:
                continue
                
            # Check gitignore
            if spec.match_file(str(relative_path)):
                continue
                
            # Check if file is binary
            if is_binary(file_path):
                continue
                
            # Calculate size
            try:
                file_size = file_path.stat().st_size
                total_size += file_size
                valid_files.append(file_path)
            except Exception:
                continue
                
    # Validate size limit
    max_bytes = settings.MAX_REPO_SIZE_MB * 1024 * 1024
    if total_size > max_bytes:
        raise ValueError(
            f"Repository size ({total_size / (1024*1024):.2f} MB) "
            f"exceeds the limit of {settings.MAX_REPO_SIZE_MB} MB."
        )
        
    return valid_files, total_size
