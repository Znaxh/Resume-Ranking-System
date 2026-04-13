"""Lazy BERT weights — safe to import; no download or load until first use."""

_models = {}
_tokenizers = {}


def get_bert_model(model_name: str = "bert-base-uncased"):
    if model_name not in _models:
        from transformers import BertModel

        m = BertModel.from_pretrained(model_name)
        m.eval()
        _models[model_name] = m
    return _models[model_name]


def get_bert_tokenizer(model_name: str = "bert-base-uncased"):
    if model_name not in _tokenizers:
        from transformers import BertTokenizer

        _tokenizers[model_name] = BertTokenizer.from_pretrained(model_name)
    return _tokenizers[model_name]
