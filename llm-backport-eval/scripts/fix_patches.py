"""
Automatically fix common issues in patch files
"""
import os
import argparse
import shutil
from pathlib import Path

def fix_patch_file(input_path, output_path=None, fixes_applied=None):
    """
    Fix common patch file issues:
    1. Convert Windows paths to Unix paths
    2. Ensure proper line endings (LF)
    3. Remove invalid lines
    4. Ensure proper structure
    """
    if fixes_applied is None:
        fixes_applied = []
    
    if output_path is None:
        output_path = input_path
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Fix 1: Convert Windows paths to Unix
        if '\\' in content:
            content = content.replace('\\', '/')
            fixes_applied.append("converted_windows_paths")
        
        # Fix 2: Normalize line endings
        lines = content.splitlines()
        
        # Fix 3: Filter and clean lines
        cleaned_lines = []
        in_hunk = False
        last_was_header = False
        
        for i, line in enumerate(lines):
            # Keep file headers
            if line.startswith('--- ') or line.startswith('+++ '):
                cleaned_lines.append(line)
                last_was_header = True
                continue
            
            # Keep hunk headers
            if line.startswith('@@ '):
                cleaned_lines.append(line)
                in_hunk = True
                last_was_header = False
                continue
            
            # Keep diff command
            if line.startswith('diff '):
                cleaned_lines.append(line)
                last_was_header = False
                continue
            
            # Keep metadata
            if line.startswith(('index ', 'new file', 'deleted file', 'similarity', 'rename')):
                cleaned_lines.append(line)
                continue
            
            # In a hunk, keep additions, deletions, and context
            if in_hunk:
                if line.startswith(('+', '-', ' ')):
                    cleaned_lines.append(line)
                elif line.strip() == '':
                    # Empty line in hunk - might be context
                    cleaned_lines.append(' ')
                else:
                    # Non-standard line, might end the hunk
                    in_hunk = False
            
            last_was_header = False
        
        if len(cleaned_lines) != len(lines):
            fixes_applied.append("removed_invalid_lines")
        
        # Fix 4: Ensure there are actual changes
        has_changes = any(
            l.startswith(('+', '-')) and not l.startswith(('+++', '---'))
            for l in cleaned_lines
        )
        
        if not has_changes:
            fixes_applied.append("no_changes_found")
            return False, fixes_applied
        
        # Write fixed content
        with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(cleaned_lines))
            if cleaned_lines and not cleaned_lines[-1].endswith('\n'):
                f.write('\n')
        
        return True, fixes_applied
        
    except Exception as e:
        fixes_applied.append(f"error: {e}")
        return False, fixes_applied

def main():
    parser = argparse.ArgumentParser(description="Fix common patch file issues")
    parser.add_argument("--patch_dir", required=True, help="Directory containing patch files")
    parser.add_argument("--output_dir", help="Output directory (default: overwrite originals)")
    parser.add_argument("--backup", action="store_true", help="Create .bak backups")
    args = parser.parse_args()
    
    patch_dir = Path(args.patch_dir)
    output_dir = Path(args.output_dir) if args.output_dir else patch_dir
    
    if args.output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
    
    patch_files = list(patch_dir.glob("*.patch"))
    
    print(f"\n{'='*80}")
    print(f"PATCH FILE FIXER")
    print(f"{'='*80}")
    print(f"Input directory:  {patch_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Total patches:    {len(patch_files)}")
    print(f"Backup originals: {args.backup}\n")
    
    fixed_count = 0
    failed_count = 0
    
    for patch_file in sorted(patch_files):
        output_file = output_dir / patch_file.name
        
        # Backup if requested
        if args.backup and output_file.exists():
            shutil.copy2(output_file, str(output_file) + '.bak')
        
        fixes = []
        success, fixes = fix_patch_file(patch_file, output_file, fixes)
        
        if success:
            if fixes:
                print(f"✅ {patch_file.name}: Fixed ({', '.join(fixes)})")
                fixed_count += 1
            else:
                print(f"✅ {patch_file.name}: OK (no fixes needed)")
        else:
            print(f"❌ {patch_file.name}: Failed ({', '.join(fixes)})")
            failed_count += 1
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Total processed: {len(patch_files)}")
    print(f"Fixed:           {fixed_count}")
    print(f"Failed:          {failed_count}")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()