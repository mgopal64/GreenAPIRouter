import json

import numpy as np
import torch
import torch.nn as nn
from huggingface_hub import PyTorchModelHubMixin, hf_hub_download
from transformers import AutoModel, AutoTokenizer

REPO = "nvidia/prompt-task-and-complexity-classifier"


class MeanPooling(nn.Module):
    def forward(self, last_hidden_state, attention_mask):
        mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        summed = torch.sum(last_hidden_state * mask, 1)
        counts = torch.clamp(mask.sum(1), min=1e-9)
        return summed / counts


class MulticlassHead(nn.Module):
    def __init__(self, input_size, num_classes):
        super().__init__()
        self.fc = nn.Linear(input_size, num_classes)

    def forward(self, x):
        return self.fc(x)


class CustomModel(nn.Module, PyTorchModelHubMixin):
    def __init__(self, target_sizes, task_type_map, weights_map, divisor_map):
        super().__init__()
        self.backbone = AutoModel.from_pretrained("microsoft/DeBERTa-v3-base")
        self.target_sizes = target_sizes.values()
        self.task_type_map = task_type_map
        self.weights_map = weights_map
        self.divisor_map = divisor_map

        self.heads = [
            MulticlassHead(self.backbone.config.hidden_size, sz)
            for sz in self.target_sizes
        ]
        for i, head in enumerate(self.heads):
            self.add_module(f"head_{i}", head)

        self.pool = MeanPooling()

    def compute_results(self, preds, target, decimal=4):
        if target == "task_type":
            top2_indices = torch.topk(preds, k=2, dim=1).indices
            probs = torch.softmax(preds, dim=1)
            top2_probs = probs.gather(1, top2_indices)
            top2 = top2_indices.detach().cpu().tolist()
            top2_prob = top2_probs.detach().cpu().tolist()

            top2_strings = [
                [self.task_type_map[str(idx)] for idx in sample] for sample in top2
            ]
            top2_prob_rounded = [[round(v, 3) for v in sub] for sub in top2_prob]

            for i, sub in enumerate(top2_prob_rounded):
                if sub[1] < 0.1:
                    top2_strings[i][1] = "NA"

            return (
                [s[0] for s in top2_strings],
                [s[1] for s in top2_strings],
                [s[0] for s in top2_prob_rounded],
            )

        preds = torch.softmax(preds, dim=1)
        weights = np.array(self.weights_map[target])
        weighted_sum = np.sum(np.array(preds.detach().cpu()) * weights, axis=1)
        scores = weighted_sum / self.divisor_map[target]
        scores = [round(v, decimal) for v in scores]
        if target == "number_of_few_shots":
            scores = [x if x >= 0.05 else 0 for x in scores]
        return scores

    def process_logits(self, logits):
        result = {}
        t1, t2, tp = self.compute_results(logits[0], target="task_type")
        result["task_type_1"], result["task_type_2"], result["task_type_prob"] = t1, t2, tp

        names = [
            "creativity_scope", "reasoning", "contextual_knowledge",
            "number_of_few_shots", "domain_knowledge", "no_label_reason",
            "constraint_ct",
        ]
        for i, name in enumerate(names, start=1):
            result[name] = self.compute_results(logits[i], target=name)

        result["prompt_complexity_score"] = [
            round(
                0.35 * cr + 0.25 * re + 0.15 * co + 0.15 * dk + 0.05 * ck + 0.05 * fs,
                5,
            )
            for cr, re, co, dk, ck, fs in zip(
                result["creativity_scope"],
                result["reasoning"],
                result["constraint_ct"],
                result["domain_knowledge"],
                result["contextual_knowledge"],
                result["number_of_few_shots"],
            )
        ]
        return result

    def forward(self, batch):
        outputs = self.backbone(
            input_ids=batch["input_ids"], attention_mask=batch["attention_mask"]
        )
        pooled = self.pool(outputs.last_hidden_state, batch["attention_mask"])
        logits = [self.heads[k](pooled) for k in range(len(self.target_sizes))]
        return self.process_logits(logits)


_tokenizer = None
_model = None


def _load():
    global _tokenizer, _model
    if _model is not None:
        return
    with open(hf_hub_download(REPO, "config.json")) as f:
        config = json.load(f)
    _tokenizer = AutoTokenizer.from_pretrained(REPO)
    _model = CustomModel(
        target_sizes=config["target_sizes"],
        task_type_map=config["task_type_map"],
        weights_map=config["weights_map"],
        divisor_map=config["divisor_map"],
    ).from_pretrained(REPO)
    _model.eval()


def nvidia_scores(prompts, batch_size=8):
    """Returns a dict of lists (one entry per prompt): prompt_complexity_score,
    reasoning, creativity_scope, constraint_ct, domain_knowledge, task_type_1, ..."""
    _load()
    merged = {}
    for start in range(0, len(prompts), batch_size):
        chunk = prompts[start:start + batch_size]
        enc = _tokenizer(
            chunk, return_tensors="pt", max_length=512,
            padding="max_length", truncation=True,
        )
        with torch.no_grad():
            out = _model(enc)
        for k, v in out.items():
            merged.setdefault(k, []).extend(v)
    return merged
