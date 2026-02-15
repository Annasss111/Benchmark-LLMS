# LLM Backport Testing

Testing different LLMs for automated backporting on 202 instances.

## Setup

1. Install stuff:
```bash
pip install docker ollama tqdm
```

2. Make sure Docker and Ollama are running

3. Pull models (if you don't have them):
```bash
ollama pull qwen2.5-coder:7b
ollama pull mistral
ollama pull gemma2
ollama pull llama3
```

## How to Run

### Test Agentless Method:
```bash
# 1. Generate patches (change model in line ~30 of script)
python scripts/llm_agentless_pure.py

# 2. Fix paths
python scripts/fix_patches.py --patch_dir llm_agentless_patches --backup
python scripts/fix_patch_paths.py --patch_dir llm_agentless_patches --backup

# 3. Evaluate
python scripts/backport_run_evaluation.py --input final_backportbench.jsonl --patch_dir llm_agentless_patches --output results/agentless_results.json --workers 4 --debug
```

### Test Oracle Method:
```bash
# 1. Generate patches (change model in line ~75 of script)
python scripts/llm_oracle_pure.py

# 2. Fix paths
python scripts/fix_patches.py --patch_dir llm_oracle_patches --backup
python scripts/fix_patch_paths.py --patch_dir llm_oracle_patches --backup

# 3. Evaluate
python scripts/backport_run_evaluation.py --input final_backportbench.jsonl --patch_dir llm_oracle_patches --output results/oracle_results.json --workers 4 --debug
```

## Change Model

Edit these lines in the scripts:

**In `llm_agentless_pure.py` (around line 30):**
```python
model='mistral',  # Change to: qwen2.5-coder:7b, gemma2, llama3
```

**In `llm_oracle_pure.py` (around line 75):**
```python
model='mistral',  # Change to: qwen2.5-coder:7b, gemma2, llama3
```

## Models to Test

- `qwen2.5-coder:7b` (best for code)
- `mistral` (baseline)
- `gemma2` (Google)
- `llama3` (Meta)

## Results

Results go in `results/` folder as JSON files.

## Notes

- 202 instances takes ~2-3 hours per model
- Clean Docker between models: `docker system prune -a`
- Use `--workers 4` to speed up (or `--workers 1` if low RAM)