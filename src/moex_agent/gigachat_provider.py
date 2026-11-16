"""Native GigaChat authentication and function calling; secrets stay in memory."""
import json
import os
import time
import uuid
from pathlib import Path

import requests

from .providers import ProviderError, ProviderResponse, ToolCall


class GigaChatProvider:
    def __init__(self, config):
        self.credentials = os.environ.get('GIGACHAT_AUTH_KEY', '').strip()
        if not self.credentials:
            raise ProviderError('Не задан GIGACHAT_AUTH_KEY (Authorization Key)')
        self.model = config.get('model', 'GigaChat')
        self.url = config.get('base_url', 'https://api.giga.chat/v1/chat/completions')
        self.scope = config.get('scope', 'GIGACHAT_API_PERS')
        self.http = requests.Session()
        bundle = config.get("ca_bundle_file")
        if bundle:
            bundle_path = Path(bundle)
            if not bundle_path.is_absolute():
                bundle_path = Path(__file__).resolve().parents[2] / bundle_path
            self.http.verify = str(bundle_path)
        self.token = None
        self.expires_at = 0
        self.states = {}

    def _request(self, method, url, **kwargs):
        stage = "авторизация" if url.endswith('/oauth') else "список моделей" if url.endswith('/models') else "ответ модели"
        attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                response = getattr(self.http, method)(url, timeout=45, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.SSLError:
                raise ProviderError(f'GigaChat ({stage}): ошибка проверки TLS-сертификата; проверка TLS обязательна') from None
            except requests.RequestException as exc:
                status = getattr(exc.response, 'status_code', None)
                retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError)) or status in (429, 500, 502, 503, 504)
                detail = f"HTTP {status}" if status else "ошибка сети или таймаут"
                if retryable and attempt < attempts:
                    print(f"  ↻ GigaChat ({stage}): {detail}; попытка {attempt + 1}/{attempts}", flush=True)
                    time.sleep(1)
                    continue
                raise ProviderError(f'GigaChat ({stage}): {detail}; попыток: {attempt}') from None

    def _post(self, url, **kwargs):
        response = self._request('post', url, **kwargs)
        try:
            return response.json()
        except ValueError:
            raise ProviderError('GigaChat: некорректный JSON') from None

    def _access_token(self):
        if not self.token or time.time() >= self.expires_at - 60:
            payload = self._post(
                'https://ngw.devices.sberbank.ru:9443/api/v2/oauth',
                headers={'Authorization': 'Basic ' + self.credentials, 'RqUID': str(uuid.uuid4()),
                         'Accept': 'application/json'},
                data={'scope': self.scope},
            )
            try:
                self.token = payload['access_token']
                self.expires_at = float(payload['expires_at']) / 1000
            except (KeyError, TypeError, ValueError):
                raise ProviderError('GigaChat: в ответе авторизации нет токена или срока действия') from None
        return self.token

    def _resolve_model(self):
        if self.model != 'auto':
            return
        try:
            response = self._request('get',
                self.url.rsplit('/chat/completions', 1)[0] + '/models',
                headers={'Authorization': 'Bearer ' + self._access_token()},
            )
            response.raise_for_status()
            models = [item['id'] for item in response.json()['data']
                      if item.get('id', '').startswith('GigaChat')]
            if not models:
                raise ProviderError('GigaChat: нет доступных моделей для чата')
            preferred = ('GigaChat-2', 'GigaChat-2-Pro', 'GigaChat-2-Max', 'GigaChat')
            self.model = next((name for name in preferred if name in models), sorted(models)[0])
            print('Модель GigaChat: ' + self.model)
        except requests.RequestException as exc:
            status = getattr(exc.response, 'status_code', None)
            raise ProviderError(f'GigaChat: список моделей HTTP {status}' if status else 'GigaChat: список моделей недоступен (TLS/сеть/таймаут)') from None
        except (KeyError, TypeError, ValueError):
            raise ProviderError('GigaChat: некорректный список моделей') from None

    def respond(self, messages, tools, session):
        self._resolve_model()
        native = []
        for message in messages:
            if message['role'] == 'tool':
                native.append({'role': 'function', 'name': message['name'], 'content': message['content']})
            elif message.get('tool_calls'):
                call = message['tool_calls'][0]
                entry = {'role': 'assistant', 'content': message.get('content') or '',
                         'function_call': {'name': call['function']['name'],
                                           'arguments': json.loads(call['function']['arguments'])}}
                if self.states.get(call['id']):
                    entry['functions_state_id'] = self.states[call['id']]
                native.append(entry)
            else:
                native.append({'role': message['role'], 'content': message.get('content') or ''})
        payload = self._post(
            self.url,
            headers={'Authorization': 'Bearer ' + self._access_token()},
            json={'model': self.model, 'messages': native,
                  'functions': [tool['function'] for tool in tools],
                  'function_call': 'auto', 'stream': False},
        )
        try:
            message = payload['choices'][0]['message']
            call = message.get('function_call')
            calls = None
            if call:
                call_id = str(uuid.uuid4())
                arguments = call['arguments']
                if not isinstance(arguments, dict):
                    raise ValueError('Invalid arguments')
                calls = [ToolCall(call['name'], arguments, call_id)]
                self.states[call_id] = message.get('functions_state_id')
            return ProviderResponse(content=message.get('content'), tool_calls=calls)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError('GigaChat: неверный формат ответа модели') from None
