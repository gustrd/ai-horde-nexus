import unicodedata
import re
from typing import Dict, Any

def apply_format_flags(text: str, params: Dict[str, Any]) -> str:
    """
    Applies Horde-specific text formatting flags manually if the backend
    doesn't natively support it.
    """
    if not text:
        return text
        
    # frmttriminc: trim incomplete sentence at the end
    if params.get("frmttriminc", False):
        # Remove anything after the last sentence terminator
        sentence_endings = ('.', '!', '?', '"', '\n')
        last_index = -1
        for char in sentence_endings:
            last_index = max(last_index, text.rfind(char))
                
        if last_index != -1:
            text = text[:last_index + 1]
            
    # frmtrmblln: remove duplicate/blank lines
    if params.get("frmtrmblln", False):
        # Collapse multiple newlines into a single one
        text = re.sub(r'\n\s*\n+', '\n', text)
        
    # frmtrmspch: remove special characters (non-printable/control chars)
    if params.get("frmtrmspch", False):
        # Keep only basic, non-control chars plus normal whitespace
        text = "".join(ch for ch in text if ch == '\n' or (not unicodedata.category(ch).startswith('C')))
        
    # frmtadsnsp: ensure a space before sentence (redundant for raw text, but compliant)
    # This is mostly for the prompt-input joining, but can be applied after-the-fact
    if params.get("frmtadsnsp", False):
        if text and not text.startswith(" "):
            text = " " + text
            
    return text

def map_params_to_koboldai(params: Dict[str, Any]) -> Dict[str, Any]:
    """Horde parameters to KoboldAI (native-like)."""
    # Most Horde params ARE KoboldAI params, so we just map specific overrides
    mapped = dict(params)
    
    # Common mappings
    if "seed" in params:
        mapped["sampler_seed"] = params["seed"]
        
    # KoboldAI specific or shared params
    # ... nothing major needed as Horde uses KoboldAI format ...
    
    return mapped

def map_params_to_openai(params: Dict[str, Any], backend_name: str = "openai") -> Dict[str, Any]:
    """Horde/KoboldAI parameters to OpenAI chat-like or completion format."""
    # Basic OpenAI mapping (base subset)
    mapped = {
        "temperature": params.get("temperature", 1.0),
        "top_p": params.get("top_p", 1.0),
        "max_tokens": params.get("max_length", 32),
        "stop": params.get("stop_sequence", []),
        "seed": params.get("seed", 0)
    }
    
    # Extensions for llama.cpp/Aphrodite
    # Repetition Penalty / Presence / Frequency
    # Frequency/Presence usually 0.0-2.0, Rep Pen 1.0-2.0
    if "rep_pen" in params:
        # Approximate: frequency_penalty is usually additive, rep_pen is multiplicative.
        # But some backends support repetition_penalty as a direct field now.
        mapped["repetition_penalty"] = params["rep_pen"]
        
    if "top_k" in params: mapped["top_k"] = params["top_k"]
    if "min_p" in params: mapped["min_p"] = params["min_p"]
    if "typical" in params: mapped["typical_p"] = params["typical"]
    if "tfs" in params: mapped["tfs_z"] = params["tfs"]
    
    # Special Mirostat settings
    if "mirostat" in params:
        mapped["mirostat_mode"] = params["mirostat"]
        mapped["mirostat_tau"] = params.get("mirostat_tau", 5.0)
        mapped["mirostat_eta"] = params.get("mirostat_eta", 0.1)

    # Special Dynatemp settings
    if "dynatemp_range" in params:
        mapped["dynatemp_range"] = params["dynatemp_range"]
        mapped["dynatemp_exponent"] = params.get("dynatemp_exponent", 1.0)

    # Special logic for Aphrodite
    if backend_name == "aphrodite":
        if "rep_pen_range" in params:
            mapped["repetition_penalty_range"] = params["rep_pen_range"]
        if "smoothing_factor" in params:
            mapped["smoothing_factor"] = params["smoothing_factor"]

    return mapped
