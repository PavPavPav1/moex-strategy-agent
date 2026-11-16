import time

import pytest
import requests

from moex_agent.gigachat_provider import GigaChatProvider
from moex_agent.providers import ProviderError


def test_auth_native_functions_and_state(monkeypatch):
    monkeypatch.setenv('GIGACHAT_AUTH_KEY', 'test-only')
    provider = GigaChatProvider({})
    calls = []
    responses = iter([
        {'access_token': 'token-only', 'expires_at': (time.time() + 1800) * 1000},
        {'choices': [{'message': {'content': '', 'function_call': {'name': 'formalize_strategy', 'arguments': {'text': 'SBER'}}, 'functions_state_id': 'state'}}]},
        {'choices': [{'message': {'content': 'готово'}}]},
    ])
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return next(responses)
    monkeypatch.setattr(provider, '_post', post)
    schemas = [{'type': 'function', 'function': {'name': 'formalize_strategy'}}]
    messages = [{'role': 'user', 'content': 'SBER'}]
    response = provider.respond(messages, schemas, None)
    call = response.tool_calls[0]
    messages.extend([
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': call.call_id, 'function': {'name': call.name, 'arguments': '{"text":"SBER"}'}}]},
        {'role': 'tool', 'name': call.name, 'tool_call_id': call.call_id, 'content': '{}'},
    ])
    assert provider.respond(messages, schemas, None).content == 'готово'
    assert len(calls) == 3  # token reused
    assert calls[0][1]['data']['scope'] == 'GIGACHAT_API_PERS'
    body = calls[-1][1]['json']
    assert body['messages'][-2]['functions_state_id'] == 'state'
    assert body['messages'][-1]['role'] == 'function'
    assert body['functions'] == [schemas[0]['function']]
    assert 'tools' not in body


def test_auth_errors_do_not_expose_key(monkeypatch):
    monkeypatch.setenv('GIGACHAT_AUTH_KEY', 'secret-test-value')
    provider = GigaChatProvider({})
    def fail(*args, **kwargs):
        raise requests.exceptions.SSLError('secret-test-value')
    monkeypatch.setattr(provider.http, 'post', fail)
    with pytest.raises(ProviderError) as error:
        provider._access_token()
    assert 'secret-test-value' not in str(error.value)
    # A transient timeout is retried, while the TLS failure above is not bypassed.
    calls = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'access_token': 'test-token', 'expires_at': (time.time() + 1800) * 1000}
    def transient(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise requests.Timeout()
        return Response()
    monkeypatch.setattr(provider.http, 'post', transient)
    monkeypatch.setattr('moex_agent.gigachat_provider.time.sleep', lambda seconds: None)
    assert provider._access_token() == 'test-token'
    assert len(calls) == 2



def test_select_available_model_not_obsolete_alias(monkeypatch):
    monkeypatch.setenv('GIGACHAT_AUTH_KEY', 'test-only')
    provider = GigaChatProvider({'model': 'auto'})
    monkeypatch.setattr(provider, '_access_token', lambda: 'token-only')
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'data': [{'id': 'Embeddings'}, {'id': 'GigaChat-2-Max'}, {'id': 'GigaChat-2'}]}
    captured = []
    def get(url, **kwargs):
        captured.append(url)
        return Response()
    monkeypatch.setattr(provider.http, 'get', get)
    provider._resolve_model()
    provider._resolve_model()
    assert provider.model == 'GigaChat-2'
    assert captured == ['https://api.giga.chat/v1/models']
