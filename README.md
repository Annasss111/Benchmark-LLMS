# LLM Backport Testing

Testing different LLMs for automated backporting on 202 instances.

## Setup

1. Install dependencies:
```bash
pip install docker ollama tqdm
```

2. Make sure Docker Desktop and Ollama are running

3. Pull Docker images (one-time setup, ~20GB):
```bash
python pull_docker_images.py
```

4. Pull LLM models:
```bash
ollama pull qwen2.5-coder:7b
ollama pull mistral
ollama pull gemma2
ollama pull llama3
```

## How to Run

### Test Agentless Method:

```bash
# 1. Generate patches (default: instances 0-202)
python scripts/llm_agentless_pure.py --start 0 --limit 202

# 2. Evaluate
python scripts/backport_run_evaluation.py \
  --input final_backportbench.jsonl \
  --patch_dir scripts/agentless_patches \
  --output results/agentless_results.json \
  --workers 4 \
  --debug
```

### Resume from Specific Instance:

If the script stops, resume from where you left off:

```bash
# Resume from instance 78
python scripts/llm_agentless_pure.py --start 78 --limit 202
```

## Change Model

Edit this line in `scripts/llm_agentless_pure.py` (around line 149):

```python
model='qwen2.5-coder:7b',  # Change to: mistral, gemma2, llama3
```

## Available Models

- `qwen2.5-coder:7b` - Best for code (recommended)
- `mistral` - Fast baseline
- `gemma2` - Google's model
- `llama3` - Meta's model

## Results

Results are saved as JSON files in the `results/` folder.

## Performance Notes

- **Time**: ~2-4 hours per model for 202 instances (depends on hardware)
- **GPU**: Strongly recommended (10-20x faster than CPU)
  - Check GPU usage: `nvidia-smi -l 1`
  - GPU should show 80-100% utilization during inference
- **RAM**: 16GB+ recommended
- **Disk**: ~30GB free space needed

## Troubleshooting

### Clean Docker Cache
Between model tests, clean up Docker:
```bash
docker system prune -a
```

### Slow Performance
- **Check GPU usage**: Run `nvidia-smi` while script is running
- **Reduce workers**: Use `--workers 1` if low on RAM
- **Use smaller model**: Try `qwen2.5-coder:3b` instead of `7b`

### Docker Issues
- Make sure Docker Desktop is running
- Restart Docker if containers fail to start
- Check disk space: `docker system df`

## Repository Structure

```
llm-backport-eval/
├── README.md                           # This file
├── .gitignore
├── final_backportbench.jsonl          # Dataset (202 instances)
├── pull_docker_images.py              # Download all Docker containers
├── scripts/
│   ├── llm_agentless_pure.py         # 100% LLM Agentless
│   ├── backport_run_evaluation.py    # Evaluation script
│   ├── agentless_patches/            # Generated patches folder
│   └── backport_log_parsers/         # Log parsing utilities
└── results/                           # Evaluation outputs
```

## Example Workflow

```bash
# 1. Pull Docker images (one time)
python pull_docker_images.py

# 2. Test with qwen2.5-coder (recommended)
python scripts/llm_agentless_pure.py --start 0 --limit 202

# 3. Evaluate results
python scripts/backport_run_evaluation.py \
  --input final_backportbench.jsonl \
  --patch_dir scripts/agentless_patches \
  --output results/qwen_results.json \
  --workers 4

# 4. Change model in scripts/llm_agentless_pure.py to 'mistral' and repeat steps 2-3
```
