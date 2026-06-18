import os
os.environ["NLLB_TRANSLATION_MODEL"] = r"C:\Users\shilob.das\practice_code\nllb-200-3.3B"

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import torch

model_path = r"C:\Users\shilob.das\practice_code\nllb-200-3.3B"

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(model_path)
print("Loading model... (this may take 1-2 minutes)")
model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
model.eval()
print("Model loaded!")

text = "Hello"
inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
target_lang_id = tokenizer.convert_tokens_to_ids("ben_Beng")
translated_tokens = model.generate(**inputs, forced_bos_token_id=target_lang_id, max_length=512)
result = tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)[0]
print(f"Translation result: {result}")