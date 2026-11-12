# Lab e1: Train a tiny GPT on a text you choose

**Goes with:** Elective "Let's Build GPT," week 4 (lessons e1-w4-l7 and e1-w4-l8), and the elective project.
**Time:** about 60 minutes for the helpers and tests, plus however long you spend on the model.

## Goal

Get everything around a character-level GPT right, and tested, before you write the model:

1. **Clean the corpus.** Strip a Project Gutenberg file down to the text of the book.
2. **Tokenize.** A character tokenizer whose `decode(encode(s)) == s` for every string in its vocabulary.
3. **Split and batch.** A contiguous 90/10 train/validation split, and random batches whose targets are the inputs shifted by one.
4. **Numerics and baselines.** A numerically stable softmax with temperature, and the uniform-model loss log V that your model must beat from step 0.

Then use `train_outline.py` to train your own GPT (written following lesson e1-w4-l7) and log loss curves for the project.

None of the helper tests needs PyTorch or an API key.

## Choosing a corpus

Use text you have the right to use: something public domain or something you wrote yourself.

- **Project Gutenberg** is the usual source. Its permissions page says most of its eBooks are in the public domain in the US, that it follows US copyright law, and that status can differ in other countries, so check if you're outside the US. The site is intended for human users and may block automated downloading (see its robot access policy), so download your book by hand from the book's page, choosing "Plain Text UTF-8." Then pass `--gutenberg` to strip the license header and footer.
- **Your own writing** (notes, essays, code you own) works well and makes the samples more fun to read.
- **Size.** One to a few megabytes of text trains in minutes on a laptop at the default settings. Tiny Shakespeare, which the lecture and nanoGPT use, is about 1 MB. Smaller corpora overfit quickly, which is itself worth seeing.

Put the file in `data/` inside this folder (create it). Don't commit copyrighted text to a public repository.

## Steps

Work in `starter.py`. The tests import from it.

1. Implement `strip_gutenberg`, `CharTokenizer.from_text`, `encode`, `decode`, `train_val_split`, `get_batch`, `stable_softmax`, and `uniform_loss`, following the docstrings.
2. Run the offline tests until they pass:

   ```bash
   cd labs && source .venv/bin/activate
   pytest electives/e1-tiny-gpt -q
   ```

   Two tests compare your functions with PyTorch and are skipped unless torch is installed.
3. Check your data pipeline without torch:

   ```bash
   cd labs/electives/e1-tiny-gpt
   python train_outline.py --corpus data/your_book.txt --gutenberg --check-data
   ```

   Read the example input and target. The target should be the input shifted left by one character.
4. Install PyTorch (`pip install torch`; see pytorch.org for the right command for your machine), write `build_model` in `train_outline.py` following the lecture, and train:

   ```bash
   python train_outline.py --corpus data/your_book.txt --gutenberg --run-name base
   ```

   Each run writes `runs/<name>.csv`, `runs/<name>-config.json`, and `runs/<name>-samples.txt`.

## Reference code (read after you write your own)

- Karpathy's [ng-video-lecture](https://github.com/karpathy/ng-video-lecture) is the code built in the lecture (MIT). Its README notes that the video skipped careful weight initialization and points to nanoGPT's `_init_weights` for that.
- Karpathy's [nanoGPT](https://github.com/karpathy/nanoGPT) (MIT) is a cleaner, faster version. As of the review date its README describes it as old and deprecated in favor of a newer project, nanochat, while keeping it available. It's still the clearest reference for this model. Its quick start trains a 6-layer, 6-head, 384-dimension model with context 256 on tiny Shakespeare and reports a best validation loss of 1.4697 after about 3 minutes on one A100 GPU, and about 1.88 for a 4-layer, 4-head, 128-dimension, context-64 CPU configuration that also runs in about 3 minutes. Use those as calibration, remembering that a different corpus has a different achievable loss.

## Expected cost

No API calls. Training at the defaults (4 layers, 4 heads, 128-dimensional embeddings, context 64, 2,000 steps) takes minutes on a recent laptop CPU, and less with a GPU or Apple Silicon (`mps`). There is no paid component.

## What to notice

- **Step 0.** The first logged loss should be close to the uniform baseline log V printed at startup. If it's much higher, your output layer starts out overconfident (lesson 5). If it's much lower, suspect leakage.
- **The gap.** Watch train and validation loss together. On a small book, the gap opens quickly; dropout and early stopping are your tools. Record both for every run.
- **Leakage checks.** The split is contiguous on purpose: a random split of overlapping windows would put nearly identical text in both sets. And a broken causal mask makes validation loss look superb while samples stay bad (lesson 7). If a number looks too good, test for these before celebrating.
- **Samples are not a metric.** Character-level samples look plausible early. Judge runs by validation loss at equal compute, and read samples for qualitative differences.
