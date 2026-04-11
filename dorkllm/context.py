# DORK Context Synthesis Module
# Builds deep codebase and structural context for the LLM

import os
from pathlib import Path

def get_codebase_summary(limit_files=20):
    """
    Returns a strategic summary of the project structure and key files.
    """
    summary = []
    summary.append("### PROJECT STRUCTURE SUMMARY")
    
    # List top level directories
    try:
        root_items = os.listdir(".")
        dirs = [d for d in root_items if os.path.isdir(d) and not d.startswith(".")]
        summary.append(f"Directories: {', '.join(dirs)}")
    except:
        pass

    # Find key configuration and documentation files
    key_files = [
        "GEMINI.md", "ADAAD_30_INNOVATIONS.md", "ARCHITECTURE.md", 
        "DORK.md", "pyproject.toml", "requirements.txt"
    ]
    
    summary.append("\n### KEY ARCHITECTURAL DOCUMENTS")
    for kf in key_files:
        if os.path.exists(kf):
            try:
                # Read just the first few lines or headers
                with open(kf, "r") as f:
                    content = f.read(500)
                    summary.append(f"- {kf}: {content[:200]}...")
            except:
                summary.append(f"- {kf}: (Found but unreadable)")

    return "\n".join(summary)

def get_git_context():
    """
    Returns recent git activity to orient the LLM.
    """
    import subprocess
    try:
        log = subprocess.check_output(
            ["git", "log", "-n", "5", "--oneline"], 
            stderr=subprocess.STDOUT, text=True
        )
        return f"\n### RECENT GIT ACTIVITY\n{log}"
    except:
        return ""

def get_innovations_context():
    """
    Retrieves the 30 innovations that define ADAAD.
    """
    innovations_path = Path("ADAAD_30_INNOVATIONS.md")
    if innovations_path.exists():
        try:
            content = innovations_path.read_text()
            # Extract innovation titles
            titles = re.findall(r"### \d+\. (.*?)\n", content)
            return f"\n### ADAAD 30 INNOVATIONS\n- " + "\n- ".join(titles[:15]) + "\n... (truncated)"
        except:
            pass
    return ""

def get_constitution_context():
    """
    Retrieves the constitutional proposals and core mandates.
    """
    const_path = Path("CONSTITUTION_PROPOSALS.md")
    if const_path.exists():
        try:
            content = const_path.read_text()
            return f"\n### CONSTITUTIONAL CONTEXT\n{content[:500]}..."
        except:
            pass
    return ""

def get_app_structure():
    """
    Provides a high-level recursive look at the core logic.
    """
    import subprocess
    try:
        # Use find to list python files in core directories
        find_cmd = "find app/ core/ adaad/ -maxdepth 2 -name '*.py' | head -n 15"
        structure = subprocess.check_output(find_cmd, shell=True, text=True)
        return f"\n### CORE APPLICATION STRUCTURE\n{structure}"
    except:
        return ""

def get_extensive_context():
    """
    Synthesizes a full context block for the Dork strategic engine.
    """
    parts = []
    parts.append(get_codebase_summary())
    parts.append(get_innovations_context())
    parts.append(get_constitution_context())
    parts.append(get_app_structure())
    parts.append(get_git_context())
    
    # Check for Dork Knowledge Base
    kb_path = Path("ui/developer/ADAADdev/dork_knowledge_base.js")
    if kb_path.exists():
        parts.append(f"\n### DORK KNOWLEDGE BASE\nLocated at {kb_path}. Use 'grep' if specific knowledge retrieval is needed.")

    return "\n".join(parts)
