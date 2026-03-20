from src.core.params import apply_format_flags, map_params_to_koboldai, map_params_to_openai

def test_apply_format_flags_trim():
    params = {"frmttriminc": True}
    text = "Hello world! This is a test. Unfinished sentence"
    assert apply_format_flags(text, params) == "Hello world! This is a test."
    
    params = {"frmttriminc": False}
    assert apply_format_flags(text, params) == text

def test_apply_format_flags_blank_lines():
    params = {"frmtrmblln": True}
    text = "Line 1\n\n\nLine 2\n \n \nLine 3"
    assert "Line 1\nLine 2\nLine 3" in apply_format_flags(text, params)

def test_apply_format_flags_special_chars():
    params = {"frmtrmspch": True}
    # \x00 is a control char
    text = "Hello\x00world"
    assert apply_format_flags(text, params) == "Helloworld"

def test_map_params_koboldai():
    params = {"temperature": 0.5, "seed": 123}
    mapped = map_params_to_koboldai(params)
    assert mapped["temperature"] == 0.5
    assert mapped["sampler_seed"] == 123

def test_map_params_openai():
    params = {"temperature": 0.8, "max_length": 20, "rep_pen": 1.1}
    mapped = map_params_to_openai(params)
    assert mapped["temperature"] == 0.8
    assert mapped["max_tokens"] == 20
    assert mapped["repetition_penalty"] == 1.1
