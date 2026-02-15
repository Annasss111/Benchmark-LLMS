import docker
import re, os, json, time, tarfile, argparse
from docker.errors import ImageNotFound, APIError
from backport_log_parsers.log_parser import LogParser, PASS_STATUS_ls, FAIL_STATUS_ls
from tqdm import tqdm
from pathlib import Path, PurePosixPath

def copy_to_container(container, src: Path, dst: Path):
    tar_path = src.with_suffix(".tar")
    with tarfile.open(tar_path, "w") as tar:
        tar.add(src, arcname=dst.name)
    with open(tar_path, "rb") as tar_file:
        data = tar_file.read()
    container.exec_run(f"mkdir -p {dst.parent}")
    container.put_archive(os.path.dirname(dst), data)
    if tar_path.exists(): tar_path.unlink()

def prepare_image(client, img_name):
    try: 
        img = client.images.get(img_name)
        return img
    except ImageNotFound:
        print(f"\n[!] Pulling {img_name}... (this may take time)")
        client.images.pull(img_name)
        return client.images.get(img_name)
    except Exception as e:
        print(f"\n[!] Image error: {e}")
        return None

def preprocess_patch(preds_file_name, patch_file_name):
    """
    Minimal preprocessing - just convert Windows paths and ensure Unix line endings.
    DO NOT filter or truncate content.
    """
    try:
        with open(preds_file_name, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Only convert Windows paths to Unix
        content = content.replace('\\', '/')
        
        # Write with Unix line endings - that's it!
        with open(patch_file_name, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
        
        # Basic validation - has diff headers and changes
        has_headers = '---' in content and '+++' in content
        has_hunks = '@@' in content
        
        return has_headers and has_hunks
    except Exception as e:
        print(f"\n[DEBUG] Preprocess error: {e}")
        return False

def get_repo_directory(instance_id):
    """Get the repository directory name from instance_id"""
    if instance_id.startswith('django'):
        return 'django'
    elif instance_id.startswith('node-tar'):
        return 'node-tar'
    elif instance_id.startswith('vite'):
        return 'vite'
    elif instance_id.startswith('glance'):
        return 'glance'
    elif instance_id.startswith('tomcat'):
        return 'tomcat'
    elif instance_id.startswith('uaa'):
        return 'uaa'
    else:
        return instance_id.split('_')[0]

def load_and_run_tar_image(instance, client, args):
    container = None
    instance_id = instance['instance_id']
    repo = instance['repo']
    
    try:
        # Parse image ID
        parts = instance_id.split("_")
        if len(parts) < 2:
            print(f"\n[!] Invalid instance_id format: {instance_id}")
            return "error"
        
        img_name = "_".join(parts[:-1])
        img_version = parts[-1]
        img_id = f'backportbench/{img_name}:{img_version}'
        
        if args.debug:
            print(f"\n[DEBUG] Loading image: {img_id} for {instance_id}")
        
        image = prepare_image(client, img_id)
        if not image: 
            return "image error"

        container = client.containers.run(
            image.id, 
            command="tail -f /dev/null", 
            detach=True, 
            tty=True, 
            remove=True
        )
        
        # Get repo directory
        repo_dir = get_repo_directory(instance_id)
        
        # 1. Tests Before
        repo_dir = get_repo_directory(instance_id)
        
        # Execute before_apply.sh using shell wrapper (exec_run needs shell for cd)
        result = container.exec_run(["/bin/sh", "-c", f"cd /{repo_dir} && sh /check/before_apply.sh"])
        
        if args.debug and result.exit_code != 0:
            print(f"[DEBUG] Test command exit code: {result.exit_code}")
        
        log_parser = LogParser(repo)
        
        # Find log files - they should be created in the repo directory
        ls_result = container.exec_run(["/bin/sh", "-c", f"ls /{repo_dir}/*.log 2>/dev/null"])
        if ls_result.exit_code == 0:
            output = ls_result.output.decode('utf-8').strip()
        else:
            # Fallback: check root directory
            ls_result = container.exec_run(["/bin/sh", "-c", "ls /*.log 2>/dev/null"])
            output = ls_result.output.decode('utf-8').strip()
        
        if not output:
            if args.debug:
                print(f"\n[!] No log files found for {instance_id}")
            container.stop(timeout=1)
            return "error"
        
        log_prefixes = re.findall(r'(?:/[^/]+/)?(run_.*)_before\.log', output)
        
        if not log_prefixes:
            if args.debug:
                print(f"\n[!] No log files found for {instance_id}")
            container.stop(timeout=1)
            return "error"
        
        before_fail = set()
        for lp in log_prefixes:
            # Try to read from repo directory first, then root
            log_found = False
            for base_path in [f"/{repo_dir}", ""]:
                log_path = f"{base_path}/{lp}_before.log"
                result = container.exec_run(f"cat {log_path}")
                if result.exit_code == 0:
                    log_text = result.output.decode('utf-8', errors='ignore')
                    log_found = True
                    break
            
            if not log_found:
                if args.debug:
                    print(f"[DEBUG] Could not find {lp}_before.log")
                continue
            try:
                res, _ = log_parser.parse_test_logs(log_text)
                before_fail |= set([i['id'] for i in res if i['status'] in FAIL_STATUS_ls])
            except Exception as e:
                if args.debug:
                    print(f"\n[DEBUG] Error parsing before logs: {e}")

        # 2. Patching
        local_patch = os.path.join(args.patch_dir, f"{instance_id}.patch")
        temp_patch = f"temp_{instance_id}.patch"
        
        if not preprocess_patch(local_patch, temp_patch):
            container.stop(timeout=1)
            return "empty patch"
        
        if args.debug:
            with open(temp_patch, 'r') as f:
                content = f.read()
                print(f"\n[DEBUG] Patch size: {len(content)} chars")
                # Show first 300 chars to verify it's not truncated
                print(f"[DEBUG] Patch start:")
                print(content[:300])
        
        copy_to_container(container, Path(temp_patch), PurePosixPath("/check/eval.patch"))
        os.remove(temp_patch)

        # Verify patch was copied
        verify = container.exec_run("cat /check/eval.patch | wc -l")
        if verify.exit_code == 0:
            lines = verify.output.decode('utf-8').strip()
            if args.debug:
                print(f"[DEBUG] Patch has {lines} lines in container")

        success_patch = False
        last_error = ""
        
        # Try different patch strategies
        patch_commands = [
            f"cd /{repo_dir} && patch --batch -p1 --fuzz=3 -i /check/eval.patch",
            f"cd / && patch --batch -p0 --fuzz=3 -i /check/eval.patch",
            f"cd /{repo_dir} && patch --batch -p0 --fuzz=3 -i /check/eval.patch",
            f"cd / && patch --batch -p1 --fuzz=3 -i /check/eval.patch",
        ]
        
        for cmd in patch_commands:
            exit_code, output = container.exec_run(f"/bin/bash -c '{cmd}'")
            output_str = output.decode('utf-8', errors='ignore')
            
            # Success if exit code is 0 AND no critical errors
            if exit_code == 0 and "FAILED" not in output_str and "can't find file" not in output_str:
                success_patch = True
                if args.debug:
                    print(f"\n[DEBUG] ✅ Patch applied: {cmd.split('&&')[0].strip()}")
                break
            else:
                last_error = output_str
        
        if not success_patch:
            print(f"\n[!] Apply Fail for {instance_id}")
            if args.debug:
                print(f"[DEBUG] All {len(patch_commands)} strategies failed")
                print(f"[DEBUG] Last error (first 500 chars):\n{last_error[:500]}")
            container.stop(timeout=1)
            return "apply fail"

        # 3. Tests After
        result = container.exec_run(["/bin/sh", "-c", f"cd /{repo_dir} && sh /check/after_apply.sh"])
        
        after_fail = set()
        for lp in log_prefixes:
            log_found = False
            for base_path in [f"/{repo_dir}", ""]:
                log_path = f"{base_path}/{lp}_after.log"
                result = container.exec_run(f"cat {log_path}")
                if result.exit_code == 0:
                    log_text = result.output.decode('utf-8', errors='ignore')
                    log_found = True
                    break
            
            if not log_found:
                if args.debug:
                    print(f"[DEBUG] Could not find {lp}_after.log")
                continue
            try:
                res, _ = log_parser.parse_test_logs(log_text)
                after_fail |= set([i['id'] for i in res if i['status'] in FAIL_STATUS_ls])
            except Exception as e:
                if args.debug:
                    print(f"\n[DEBUG] Error parsing after logs: {e}")

        # Resolve Logic
        F2P = list(before_fail - after_fail)
        
        if args.debug:
            print(f"\n[DEBUG] {instance_id}: Before={len(before_fail)}, After={len(after_fail)}, F2P={len(F2P)}")
        
        container.stop(timeout=1)
        return F2P
        
    except Exception as e:
        print(f"\n[!] System Error for {instance_id}: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        if container: 
            try:
                container.stop(timeout=1)
            except:
                pass
        return "error"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--patch_dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    with open(args.input, 'r', encoding='utf-8') as f:
        data = [json.loads(l) for l in f if l.strip()]

    patch_dir = os.path.normpath(args.patch_dir)
    available_patches = set([f.replace(".patch", "") for f in os.listdir(patch_dir) if f.endswith(".patch")])
    
    to_eval = [i for i in data if i['instance_id'] in available_patches]
    print(f"Found {len(to_eval)} patches in {patch_dir}")

    client = docker.from_env()
    results = {
        'success': [], 
        'fail': [], 
        'apply_fail': 0,
        'errors': 0,
        'empty_patch': 0,
        'details': {}
    }

    for ins in tqdm(to_eval, colour="GREEN"):
        res = load_and_run_tar_image(ins, client, args)
        
        if res == "apply fail":
            results['apply_fail'] += 1
            results['details'][ins['instance_id']] = "apply_fail"
        elif res == "error":
            results['errors'] += 1
            results['details'][ins['instance_id']] = "error"
        elif res == "empty patch":
            results['empty_patch'] += 1
            results['details'][ins['instance_id']] = "empty_patch"
        elif isinstance(res, list):
            expected_f2p = set(ins.get('FAIL TO PASS', []))
            actual_f2p = set(res)
            
            if expected_f2p.issubset(actual_f2p) and len(actual_f2p) > 0:
                results['success'].append(ins['instance_id'])
                results['details'][ins['instance_id']] = {
                    'status': 'success',
                    'expected': list(expected_f2p),
                    'actual': list(actual_f2p)
                }
            else:
                results['fail'].append(ins['instance_id'])
                results['details'][ins['instance_id']] = {
                    'status': 'fail',
                    'expected': list(expected_f2p),
                    'actual': list(actual_f2p)
                }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4)
    
    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY:")
    print(f"{'='*60}")
    print(f"Success:      {len(results['success'])} / {len(to_eval)}")
    print(f"Fail:         {len(results['fail'])}")
    print(f"Apply Fail:   {results['apply_fail']}")
    print(f"Empty Patch:  {results['empty_patch']}")
    print(f"Errors:       {results['errors']}")
    print(f"{'='*60}")