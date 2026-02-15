"""
Fix patch file paths to match the actual container directory structure.
Based on inspection, files are at:
- Django projects: /django/...
- Node-tar: /node-tar/lib/...
- Vite: /vite/packages/vite/src/...
- etc.

Your patches currently have: a/django/... or a/lib/...
They need to be: django/... or node-tar/lib/... (without the 'a/' prefix)
"""
import os
import argparse
import re
from pathlib import Path

# Map instance prefixes to their container directory structure
REPO_PATH_MAPPINGS = {
    'django': 'django',
    'node-tar': 'node-tar',
    'vite': 'vite',
    'glance': 'glance',
    'tomcat': 'tomcat',
    'uaa': 'uaa'
}

def fix_patch_paths(patch_content, instance_id):
    """
    Fix patch paths to match container structure.
    
    Changes:
    - --- a/django/... -> --- /django/...
    - +++ b/django/... -> +++ /django/...
    
    OR for repos where files aren't in a top-level dir:
    - --- a/lib/... -> --- /node-tar/lib/...
    """
    lines = patch_content.split('\n')
    fixed_lines = []
    
    # Determine the repo from instance_id
    repo_prefix = None
    for key in REPO_PATH_MAPPINGS:
        if instance_id.startswith(key):
            repo_prefix = key
            break
    
    if not repo_prefix:
        # Try to extract from instance_id (e.g., "django_528" -> "django")
        parts = instance_id.split('_')
        if len(parts) >= 1:
            repo_prefix = parts[0]
    
    base_dir = REPO_PATH_MAPPINGS.get(repo_prefix, repo_prefix)
    
    for line in lines:
        if line.startswith('--- a/'):
            # Extract the path after 'a/'
            path = line[6:].split()[0] if ' ' in line[6:] else line[6:]
            
            # Check if path already starts with the repo name
            if path.startswith(f'{base_dir}/'):
                # Already correct, just remove the 'a/' prefix
                fixed_line = f'--- /{path}'
            else:
                # Need to prepend base_dir
                fixed_line = f'--- /{base_dir}/{path}'
            
            fixed_lines.append(fixed_line)
        elif line.startswith('+++ b/'):
            # Extract the path after 'b/'
            path = line[6:].split()[0] if ' ' in line[6:] else line[6:]
            
            # Check if path already starts with the repo name
            if path.startswith(f'{base_dir}/'):
                # Already correct, just remove the 'b/' prefix
                fixed_line = f'+++ /{path}'
            else:
                # Need to prepend base_dir
                fixed_line = f'+++ /{base_dir}/{path}'
            
            fixed_lines.append(fixed_line)
        else:
            fixed_lines.append(line)
    
    return '\n'.join(fixed_lines)

def main():
    parser = argparse.ArgumentParser(description="Fix patch file paths for container structure")
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
    print(f"PATCH PATH FIXER")
    print(f"{'='*80}")
    print(f"Input directory:  {patch_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Total patches:    {len(patch_files)}")
    print(f"Backup originals: {args.backup}\n")
    
    fixed_count = 0
    
    for patch_file in sorted(patch_files):
        instance_id = patch_file.stem
        output_file = output_dir / patch_file.name
        
        try:
            # Read original patch
            with open(patch_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Backup if requested
            if args.backup and output_file.exists():
                import shutil
                shutil.copy2(output_file, str(output_file) + '.path.bak')
            
            # Fix paths
            fixed_content = fix_patch_paths(content, instance_id)
            
            # Check if anything changed
            if fixed_content != content:
                # Write fixed patch
                with open(output_file, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(fixed_content)
                
                print(f"✅ {patch_file.name}: Fixed paths")
                fixed_count += 1
            else:
                print(f"⚪ {patch_file.name}: No changes needed")
                
        except Exception as e:
            print(f"❌ {patch_file.name}: Error - {e}")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Total processed: {len(patch_files)}")
    print(f"Fixed:           {fixed_count}")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()