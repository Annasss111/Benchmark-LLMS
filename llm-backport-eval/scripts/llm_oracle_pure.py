#!/usr/bin/env python3
"""
100% LLM ORACLE BACKPORTER
Pure LLM with ground-truth context + intelligent post-processing

Oracle: Provides exact changes from source patch
LLM: Applies them to old code
Post-Processor: Fixes output to valid unified diff
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

# ==================== ORACLE: EXTRACT GROUND TRUTH ====================

def extract_oracle_changes(source_patch, file_path):
    """
    Extract EXACT ground-truth changes from source patch.
    Returns lists of additions and deletions.
    """
    lines = source_patch.split('\n')
    in_file = False
    
    additions = []
    deletions = []
    context_lines = []
    
    for line in lines:
        if line.startswith('---') and file_path in line:
            in_file = True
            continue
        
        if in_file and line.startswith('---') and file_path not in line:
            break
        
        if in_file:
            if line.startswith('+') and not line.startswith('+++'):
                additions.append(line[1:])
            elif line.startswith('-') and not line.startswith('---'):
                deletions.append(line[1:])
            elif line.startswith(' ') and len(line) > 1:
                context_lines.append(line[1:])
    
    return {
        'additions': additions,
        'deletions': deletions,
        'context': context_lines
    }

# ==================== LLM ORACLE REPAIR ====================

def llm_oracle_repair(oracle_changes, old_code, file_path):
    """
    100% LLM Oracle Repair
    LLM sees exact changes and applies them
    """
    additions = oracle_changes['additions']
    deletions = oracle_changes['deletions']
    context = oracle_changes['context']
    
    if not additions and not deletions:
        return None
    
    # Find relevant section using context
    old_lines = old_code.split('\n')
    start_idx = 0
    
    if context:
        context_str = context[0].strip()
        for i, line in enumerate(old_lines):
            if context_str in line:
                start_idx = max(0, i - 10)
                break
    
    end_idx = min(len(old_lines), start_idx + 100)
    code_section = '\n'.join(old_lines[start_idx:end_idx])
    
    system_msg = """You are a precise code modifier with ORACLE knowledge.

You are given:
1. EXACT lines to ADD (from security patch)
2. EXACT lines to REMOVE (if any)
3. The OLD CODE section to modify

CRITICAL RULES:
- Add the lines exactly where they logically belong
- Remove specified lines if present
- Preserve ALL other code exactly
- Match indentation of surrounding code
- Use \\w not /w, \\d not /d in regex
- Output ONLY the modified code section (no explanations, no markdown)"""

    additions_str = '\n'.join([f"ADD: {line}" for line in additions[:15]])
    deletions_str = '\n'.join([f"REMOVE: {line}" for line in deletions[:15]])
    
    user_prompt = f"""ORACLE REPAIR - {file_path}

EXACT CHANGES (ground truth):
{additions_str}
{deletions_str if deletions else '(no removals)'}

OLD CODE SECTION:
{code_section}

Output ONLY the modified code section with changes applied:"""

    try:
        response = ollama.chat(
            model='qwen2.5-coder:7b',
            messages=[
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_prompt}
            ],
            options={'temperature': 0.0}
        )
        
        return response['message']['content'], start_idx, end_idx
        
    except Exception as e:
        print(f"    [!] LLM error: {e}")
        return None, None, None

# ==================== POST-PROCESSOR ====================

def clean_llm_output(llm_output):
    """Remove markdown and explanatory text"""
    if not llm_output:
        return ""
    
    # Remove markdown
    cleaned = re.sub(r'```[a-z]*\n?', '', llm_output)
    cleaned = re.sub(r'```', '', cleaned)
    
    # Remove common preambles
    lines = cleaned.split('\n')
    code_lines = []
    skip_next = False
    
    for line in lines:
        lower = line.lower()
        # Skip explanatory lines
        if any(phrase in lower for phrase in ['here is', 'here\'s', 'modified', 'output:', 'i\'ve added', 'i added']):
            skip_next = True
            continue
        if skip_next and line.strip():
            skip_next = False
        if not skip_next:
            code_lines.append(line)
    
    return '\n'.join(code_lines).strip()

def fix_regex_patterns(code):
    """Fix LLM regex escape errors"""
    # /w → \w
    code = re.sub(r'(["\'])([^"\']*)/w', r'\1\2\\w', code)
    # /d → \d  
    code = re.sub(r'(["\'])([^"\']*)/d', r'\1\2\\d', code)
    # /s → \s
    code = re.sub(r'(["\'])([^"\']*)/s', r'\1\2\\s', code)
    
    return code

def create_unified_diff_from_section(old_code, modified_section, start_idx, end_idx, file_path):
    """
    Merge modified section back into full code and generate diff
    """
    old_lines = old_code.split('\n')
    
    # Replace the section
    new_lines = old_lines.copy()
    modified_lines = modified_section.split('\n')
    
    # Replace section
    new_lines[start_idx:end_idx] = modified_lines
    
    # Generate diff
    diff_lines = list(unified_diff(
        old_lines,
        new_lines,
        fromfile=f'a/{file_path}',
        tofile=f'b/{file_path}',
        lineterm=''
    ))
    
    if len(diff_lines) > 2:
        return '\n'.join(diff_lines)
    
    return None

# ==================== MAIN PIPELINE ====================

def llm_oracle_backport(source_patch, instance_id, repo):
    """
    100% LLM Oracle Pipeline
    1. Extract ground-truth (Oracle)
    2. LLM applies changes
    3. Post-process to valid diff
    """
    print(f"  [100% LLM Oracle] {instance_id}")
    
    # Extract files
    files = list(set(re.findall(r'(?:---|\+\+\+) [ab]/(.*?)(?:\s|$)', source_patch, re.MULTILINE)))
    files = [f for f in files if 'test' not in f.lower() and '.txt' not in f.lower()]
    
    if not files:
        print(f"    ✗ No files found")
        return None
    
    print(f"    → Files: {files}")
    
    all_patches = ""
    
    for file_path in files:
        print(f"  [Oracle LLM] {file_path}")
        
        # Get old code
        old_code = get_file_from_docker(instance_id, repo, file_path)
        if not old_code:
            print(f"    ✗ File not found")
            continue
        
        # STEP 1: Extract ground truth
        oracle_changes = extract_oracle_changes(source_patch, file_path)
        
        if not oracle_changes['additions'] and not oracle_changes['deletions']:
            print(f"    ✗ No oracle changes")
            continue
        
        print(f"    → Oracle: {len(oracle_changes['additions'])} adds, {len(oracle_changes['deletions'])} removes")
        
        # STEP 2: LLM Repair
        llm_output, start_idx, end_idx = llm_oracle_repair(oracle_changes, old_code, file_path)
        
        if not llm_output:
            print(f"    ✗ LLM failed")
            continue
        
        # STEP 3: Post-Process
        cleaned = clean_llm_output(llm_output)
        cleaned = fix_regex_patterns(cleaned)
        
        patch = create_unified_diff_from_section(old_code, cleaned, start_idx, end_idx, file_path)
        
        if patch:
            all_patches += patch + "\n"
            print(f"    ✓ Success")
        else:
            print(f"    ✗ Post-processing failed")
    
    return all_patches if all_patches.strip() else None

# ==================== MAIN ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="100% LLM Oracle")
    parser.add_argument("--limit", type=int, default=202)
    parser.add_argument("--input", default='final_backportbench.jsonl')
    parser.add_argument("--output_dir", default="llm_oracle_patches")
    args = parser.parse_args()
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    print("="*70)
    print("100% LLM ORACLE BACKPORTER")
    print("Pure LLM: Oracle Ground-Truth + Repair + Post-Processing")
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
        
        patch = llm_oracle_backport(source_patch, instance_id, repo)
        
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