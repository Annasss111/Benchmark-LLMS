#!/usr/bin/env python3
"""
100% LLM AGENTLESS BACKPORTER
Pure LLM approach with intelligent post-processing to fix LLM output

Pipeline:
1. LLM Localization - finds files and functions
2. LLM Repair - generates modified code
3. Post-Processor - converts LLM output to valid unified diff
"""

import json
import docker
import ollama
import os
import re
from difflib import unified_diff

client = docker.from_env()

def get_file_from_docker(instance_id, repo, path):
    """Get file from container"""
    parts = instance_id.split('_')
    repo_name = "_".join(parts[:-1])
    tag = parts[-1]
    img_full_name = f"backportbench/{repo_name}:{tag}"
    
    try:
        container = client.containers.run(img_full_name, detach=True, tty=True, command="tail -f /dev/null")
        for base in [f"/{repo}", f"/{repo_name}", "/"]:
            exit_code, output = container.exec_run(["/bin/sh", "-c", f"cat {base}/{path}"])
            if exit_code == 0:
                content = output.decode('utf-8')
                container.stop()
                container.remove()
                return content
        container.stop()
        container.remove()
    except:
        pass
    return None

# ==================== LLM STEP 1: LOCALIZATION ====================

def llm_localize_files(source_patch):
    """LLM identifies which files need modification"""
    system_msg = "You extract file paths from patches. Output ONLY a JSON array of file paths."
    
    user_prompt = f"""Extract all non-test file paths from this patch:

{source_patch[:1500]}

Output ONLY a JSON array: ["path1", "path2"]"""

    try:
        response = ollama.chat(
            model='qwen2.5-coder:7b',
            messages=[
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_prompt}
            ],
            options={'temperature': 0.1}
        )
        
        content = response['message']['content']
        # Extract JSON array
        match = re.search(r'\[.*?\]', content, re.DOTALL)
        if match:
            files = json.loads(match.group(0))
            return [f for f in files if 'test' not in f.lower()]
        
    except:
        pass
    
    # Fallback: regex extraction
    return list(set(re.findall(r'(?:---|\+\+\+) [ab]/(.*?)(?:\s|$)', source_patch)))

# ==================== LLM STEP 2: REPAIR ====================

def llm_generate_backport(source_patch, old_code, file_path):
    """
    100% LLM: Generate backported code
    LLM sees source patch and old code, generates new code
    """
    system_msg = """You are a security backporting expert.

TASK: Apply security fixes from a newer version to an older version.

RULES:
1. Read the SOURCE PATCH to understand what security fix was added
2. Apply the same logic to the OLD CODE
3. Output ONLY the complete modified code (no explanations)
4. Preserve all existing code structure
5. Use \\w not /w, \\d not /d in regex patterns
6. Match indentation exactly"""

    # Extract what changed from source patch
    additions = []
    for line in source_patch.split('\n'):
        if line.startswith('+') and not line.startswith('+++'):
            additions.append(line[1:])
    
    additions_preview = '\n'.join(additions[:15])
    
    user_prompt = f"""BACKPORT TASK

File: {file_path}

SOURCE PATCH (newer version):
Shows these security additions:
{additions_preview}

OLD CODE (target version to fix):
```
{old_code[:2500]}
```

Output the COMPLETE modified OLD CODE with security fix applied.
Start your response with the first line of code:
```"""

    try:
        response = ollama.chat(
            model='qwen2.5-coder:7b',
            messages=[
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_prompt}
            ],
            options={'temperature': 0.0}
        )
        
        return response['message']['content']
        
    except Exception as e:
        print(f"    [!] LLM error: {e}")
        return None

# ==================== POST-PROCESSOR: FIX LLM OUTPUT ====================

def clean_llm_code_output(llm_output):
    """Clean LLM output to extract just the code"""
    # Remove markdown code blocks
    cleaned = re.sub(r'```[a-z]*\n', '', llm_output)
    cleaned = re.sub(r'```', '', cleaned)
    
    # Remove common LLM preambles
    lines = cleaned.split('\n')
    code_started = False
    code_lines = []
    
    for line in lines:
        # Skip explanatory text
        if not code_started:
            if line.strip() and not any(phrase in line.lower() for phrase in ['here is', 'here\'s', 'i\'ve', 'the modified', 'output:']):
                code_started = True
                code_lines.append(line)
        else:
            code_lines.append(line)
    
    return '\n'.join(code_lines).strip()

def fix_regex_escapes(code):
    """Fix common LLM regex escape errors"""
    # Fix /w → \w
    code = re.sub(r'r"([^"]*)/w', r'r"\1\\w', code)
    code = re.sub(r"r'([^']*)/w", r"r'\1\\w", code)
    # Fix /d → \d
    code = re.sub(r'r"([^"]*)/d', r'r"\1\\d', code)
    code = re.sub(r"r'([^']*)/d", r"r'\1\\d", code)
    # Fix /s → \s
    code = re.sub(r'r"([^"]*)/s', r'r"\1\\s', code)
    
    return code

def merge_and_create_diff(old_code, llm_output, file_path):
    """
    POST-PROCESSOR: Convert LLM output to valid unified diff
    
    Steps:
    1. Clean LLM output
    2. Fix regex escapes
    3. Generate unified diff
    4. Validate diff format
    """
    # Step 1: Clean
    new_code = clean_llm_code_output(llm_output)
    
    # Step 2: Fix escapes
    new_code = fix_regex_escapes(new_code)
    
    # Step 3: If LLM only gave partial code, try to merge
    if len(new_code) < len(old_code) * 0.5:
        # LLM probably gave just the changed section
        # Try to find where it goes in old code
        old_lines = old_code.split('\n')
        new_lines = new_code.split('\n')
        
        # Find first matching line
        if new_lines:
            first_new = new_lines[0].strip()
            for i, old_line in enumerate(old_lines):
                if first_new in old_line:
                    # Replace from here
                    end_idx = min(i + len(new_lines), len(old_lines))
                    old_lines[i:end_idx] = new_lines
                    new_code = '\n'.join(old_lines)
                    break
    
    # Step 4: Generate diff
    old_lines = old_code.split('\n')
    new_lines = new_code.split('\n')
    
    diff_lines = list(unified_diff(
        old_lines,
        new_lines,
        fromfile=f'a/{file_path}',
        tofile=f'b/{file_path}',
        lineterm=''
    ))
    
    # Step 5: Validate
    if len(diff_lines) <= 2:
        return None
    
    # Check if diff looks valid
    has_header = any(l.startswith('---') for l in diff_lines[:3])
    has_hunks = any(l.startswith('@@') for l in diff_lines)
    has_changes = any(l.startswith(('+', '-')) for l in diff_lines)
    
    if has_header and has_hunks and has_changes:
        return '\n'.join(diff_lines)
    
    return None

# ==================== MAIN PIPELINE ====================

def llm_agentless_backport(source_patch, instance_id, repo):
    """
    100% LLM Agentless Pipeline
    1. LLM Localization
    2. LLM Repair
    3. Post-Process to valid diff
    """
    print(f"  [100% LLM Agentless] {instance_id}")
    
    # STEP 1: LLM Localization
    files = llm_localize_files(source_patch)
    
    if not files:
        print(f"    ✗ LLM found no files")
        return None
    
    print(f"    → LLM localized: {files}")
    
    all_patches = ""
    
    for file_path in files:
        print(f"  [LLM Repair] {file_path}")
        
        # Get old code
        old_code = get_file_from_docker(instance_id, repo, file_path)
        if not old_code:
            print(f"    ✗ File not found")
            continue
        
        # STEP 2: LLM Repair
        llm_output = llm_generate_backport(source_patch, old_code, file_path)
        
        if not llm_output:
            print(f"    ✗ LLM generation failed")
            continue
        
        # STEP 3: Post-Process
        patch = merge_and_create_diff(old_code, llm_output, file_path)
        
        if patch:
            all_patches += patch + "\n"
            print(f"    ✓ Success")
        else:
            print(f"    ✗ Post-processing failed")
    
    return all_patches if all_patches.strip() else None

# ==================== MAIN ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="100% LLM Agentless")
    parser.add_argument("--limit", type=int, default=202)
    parser.add_argument("--input", default='final_backportbench.jsonl')
    parser.add_argument("--output_dir", default="llm_agentless_patches")
    args = parser.parse_args()
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    print("="*70)
    print("100% LLM AGENTLESS BACKPORTER")
    print("Pure LLM: Localization + Repair + Post-Processing")
    print(f"Processing: {args.limit} instances")
    print("="*70)
    print()
    
    stats = {'success': 0, 'fail': 0}
    
    with open(args.input, 'r', encoding='utf-8') as f:
        instances = [json.loads(line) for line in f if line.strip()]
    
    for i, data in enumerate(instances[:args.limit]):
        instance_id = data['instance_id']
        repo = data['repo']
        source_patch = data.get('hints', '')
        
        print(f"\n[{i+1}/{args.limit}] {instance_id}")
        print("-" * 70)
        
        patch = llm_agentless_backport(source_patch, instance_id, repo)
        
        if patch:
            save_path = os.path.join(args.output_dir, f"{instance_id}.patch")
            with open(save_path, "w", encoding='utf-8') as f:
                f.write(patch)
            print(f"  💾 SAVED")
            stats['success'] += 1
        else:
            print(f"  ❌ FAILED")
            stats['fail'] += 1
    
    print("\n" + "="*70)
    print(f"RESULTS: {stats['success']}/{args.limit} successful")
    print(f"Saved to: {args.output_dir}/")
    print("="*70)