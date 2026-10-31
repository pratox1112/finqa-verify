# Building the search index on a free GPU

The index embeds about 177,000 chunks with `BAAI/bge-base-en-v1.5`. A laptop CPU takes about 16 hours; a free Kaggle GPU takes about 20 minutes. The result is a `chroma/` folder that goes into `data/chroma/` on your machine (gitignored; share it through the shared artifact location).

The code is the same as the local build (`src/finqa/ingestion/index.py`), and so is the model. GPU and CPU vectors differ only by rounding.

## Before you start (on your machine)

1. Build the chunks if you haven't: `uv run python -m finqa.ingestion.chunk` (about 30 seconds).
2. Zip them (PowerShell, from the repo root): `Compress-Archive -Path data/chunks -DestinationPath chunks.zip`
3. Make sure the branch with `index.py` is pushed; the notebook clones it from GitHub.

## On Kaggle

1. Sign in at kaggle.com. Under *Settings*, verify your phone number; notebooks need it for internet and GPU access.
2. **Upload the chunks:** *Create → New Dataset*, upload `chunks.zip`, name it `finqa-chunks`, keep it **Private**, *Create*. Kaggle unzips it.
3. **Create a notebook:** *Create → New Notebook*. In the right panel:
   - *Session options → Accelerator:* **GPU T4 x2** (or P100)
   - *Session options → Internet:* **On**
   - *Input → Add Input:* your `finqa-chunks` dataset
4. Paste each block below into its own cell and run them in order.

```python
# 1. Get the code (public repo) and the two extra packages; Kaggle already has torch with CUDA
!git clone --depth 1 --branch data-prep https://github.com/pratox1112/finqa-verify.git
%cd finqa-verify
!pip install -q "chromadb==1.5.9" "sentence-transformers==6.2.0" pydantic-settings httpx pyyaml
```

```python
# 2. Find the uploaded chunks folder
import glob
chunks = [p for p in glob.glob("/kaggle/input/**/chunks", recursive=True)][0]
print(chunks, len(glob.glob(chunks + "/*/*.jsonl")), "filings")   # expect 819 filings
```

```python
# 3. Build (about 20 minutes; progress prints per filing)
!PYTHONPATH=src python -m finqa.ingestion.index --device cuda --batch-size 128 --chunks-dir "{chunks}" --index-dir /kaggle/working/chroma
```

```python
# 4. Zip the index for download
!cd /kaggle/working && zip -qr chroma.zip chroma && ls -lh chroma.zip
```

5. Download `chroma.zip` from the *Output* panel on the right (`/kaggle/working`).

If the session stops midway, run the cells again; the build skips filings already finished (`indexed.txt`).

## Back on your machine

From the repo root in PowerShell:

```powershell
Remove-Item -Recurse -Force data/chroma
Expand-Archive chroma.zip -DestinationPath data
uv run python -m finqa.ingestion.index --check
```

`--check` prints the number of chunks (about 177,000) and the top three hits for 3M's FY2018 capital expenditure, filtered to 3M's FY2018 10-K, Item 8.
