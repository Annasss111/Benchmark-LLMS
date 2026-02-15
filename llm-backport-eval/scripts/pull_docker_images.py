#!/usr/bin/env python3
"""
Pull all BackportBench Docker images
"""
import json
import docker
from tqdm import tqdm

def pull_docker_images(jsonl_file='final_backportbench.jsonl'):
    """Pull all Docker images referenced in the dataset"""
    client = docker.from_env()
    
    # Extract unique images
    images = set()
    with open(jsonl_file, 'r') as f:
        for line in f:
            data = json.loads(line)
            instance_id = data['instance_id']
            parts = instance_id.split('_')
            repo_name = "_".join(parts[:-1])
            tag = parts[-1]
            images.add(f'backportbench/{repo_name}:{tag}')
    
    print(f"Found {len(images)} unique Docker images to pull")
    print("This will download ~20GB of data. Continue? (y/n)")
    
    if input().lower() != 'y':
        print("Cancelled")
        return
    
    print("\nPulling images...")
    
    for img in tqdm(images):
        try:
            print(f"\nPulling: {img}")
            client.images.pull(img)
            print(f"✅ {img}")
        except Exception as e:
            print(f"❌ Failed to pull {img}: {e}")
    
    print("\n✅ All images pulled successfully!")

if __name__ == "__main__":
    pull_docker_images()
