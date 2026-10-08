"""版本化科研对象；模型输出必须经过相同的结构与来源校验。"""
from __future__ import annotations

from datetime import datetime, date
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import hashlib
import json
import re


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class EvidenceRef(Strict):
    id: str
    version: int = Field(ge=1)


class Project(Strict):
    title: str = Field(min_length=1, max_length=120)
    question: str = Field(default='', max_length=5000)
    baseline: str = ''
    bottleneck: str = ''
    goals: str = ''
    constraints: str = ''
    timezone: str = 'Asia/Shanghai'
    audience: Literal['student', 'engineer'] = 'student'
    style: Literal['ask', 'academic', 'paper', 'lab'] = 'ask'
    demo: bool = False
    search_consent: bool = False
    model_consent: bool = False

    @field_validator('timezone')
    @classmethod
    def timezone_valid(cls, value):
        ZoneInfo(value)
        return value


class Note(Strict):
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=20000)
    category: Literal['progress', 'question', 'hypothesis', 'blocker', 'decision', 'lesson'] = 'progress'
    refs: list[EvidenceRef] = Field(default_factory=list, max_length=100)
    reviewed: bool = False
    visibility: Literal['dev', 'final'] = 'dev'


class Symbol(Strict):
    symbol: str
    meaning: str
    shape: str = '未在来源中明确'


class Formula(Strict):
    title: str
    latex: str = Field(max_length=12000)
    number: str = ''
    source: str
    symbols: list[Symbol] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    asset: str = ''
    page: int | None = Field(default=None, ge=1)
    intuition: str = ''
    limitation: str = ''
    derivation: Literal['source', 'teaching'] = 'teaching'
    reviewed: bool = False


class Region(Strict):
    label: str
    explanation: str
    box: tuple[float, float, float, float] | None = None

    @field_validator('box')
    @classmethod
    def box_valid(cls, value):
        if value and (any(v < 0 or v > 1 for v in value) or value[2] <= 0 or value[3] <= 0
                      or value[0] + value[2] > 1.001 or value[1] + value[3] > 1.001):
            raise ValueError('区域必须是原图内的归一化 x/y/width/height')
        return value


class Figure(Strict):
    title: str
    asset: str = ''
    caption: str
    source: str
    regions: list[Region] = Field(default_factory=list)
    takeaway: str = ''
    kind: Literal['original', 'crop', 'teaching'] = 'original'


class CodeBlock(Strict):
    title: str
    code: str = Field(max_length=30000)
    language: str = 'python'
    location: str = '教学伪代码'
    explanation: list[str] = Field(default_factory=list)
    formula: str = ''
    status: Literal['static', 'executed', 'teaching'] = 'static'


class Reading(Strict):
    title: str
    paper_id: str
    refs: list[EvidenceRef] = Field(min_length=1)
    summary: str
    motivation: str = ''
    contribution: list[str] = Field(default_factory=list)
    formulas: list[Formula] = Field(default_factory=list, max_length=50)
    figures: list[Figure] = Field(default_factory=list, max_length=50)
    code: list[CodeBlock] = Field(default_factory=list, max_length=30)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    demo: bool = False


class ExperimentSpec(Strict):
    title: str = Field(min_length=1, max_length=160)
    hypothesis: str = Field(min_length=8, max_length=5000)
    refs: list[EvidenceRef] = Field(default_factory=list)
    snapshot_id: str
    remote_id: str
    train_entry: str
    smoke_entry: str
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    seeds: list[int] = Field(default_factory=lambda: [42], min_length=1, max_length=8)
    dataset: str = Field(min_length=1)
    data_manifest: dict[str, str] = Field(min_length=1)
    metric: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_.-]{0,63}$')
    direction: Literal['max', 'min'] = 'max'
    threshold: float
    min_delta: float = Field(default=0.0, ge=0)
    timeout_seconds: int = Field(ge=10, le=604800)
    gpu_hours: float = Field(gt=0, le=10000)
    gpu_ids: list[int] = Field(default_factory=lambda: [0], min_length=1, max_length=16)
    protocol: str = Field(min_length=5)
    checkpoint: str = 'checkpoint.bin'
    phase: Literal['dev', 'final'] = 'dev'
    final_from: str | None = None

    @field_validator('train_entry', 'smoke_entry', 'checkpoint')
    @classmethod
    def entry_valid(cls, value):
        if not re.fullmatch(r'[A-Za-z0-9_./-]+', value) or value.startswith('/') or '..' in value.split('/'):
            raise ValueError('入口必须是快照内的安全相对路径')
        return value

    @field_validator('data_manifest')
    @classmethod
    def manifest_valid(cls, value):
        for path, checksum in value.items():
            if not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/')):
                raise ValueError('数据清单路径必须位于授权数据目录内')
            if not re.fullmatch(r'[a-f0-9]{64}', checksum):
                raise ValueError('数据清单必须包含实际 SHA256，不能使用占位文字')
        return value

    @field_validator('parameters')
    @classmethod
    def params_valid(cls, value):
        if any(not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', key) for key in value):
            raise ValueError('非法参数名称')
        if {'seed', 'output-dir', 'split', 'checkpoint', 'device'} & set(value):
            raise ValueError('保留参数由执行器管理')
        if len(value) > 100:
            raise ValueError('参数过多')
        return value

    @model_validator(mode='after')
    def unique_seeds(self):
        if len(set(self.seeds)) != len(self.seeds) or min(self.seeds) < 0 or min(self.gpu_ids) < 0 or len(set(self.gpu_ids)) != len(self.gpu_ids):
            raise ValueError('种子须唯一，GPU ID 不可为负')
        if self.phase == 'final' and not self.final_from:
            raise ValueError('最终测试必须绑定已冻结的开发实验')
        return self


class RemoteConfig(Strict):
    title: str
    alias: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$')
    root: str = Field(pattern=r'^/[A-Za-z0-9_./-]+$')
    python: str = Field(pattern=r'^/[A-Za-z0-9_./-]+$')
    dataset_root: str = Field(pattern=r'^/[A-Za-z0-9_./-]+$')
    consent: bool = False
    isolation: Literal['protocol', 'separate-account'] = 'protocol'

    @field_validator('root', 'python', 'dataset_root')
    @classmethod
    def no_traversal(cls, value):
        if '..' in value.split('/') or value == '/':
            raise ValueError('必须指定受控子目录/解释器路径')
        return value


class ModelConfig(Strict):
    base_url: str = 'https://api.openai.com/v1'
    model: str = ''
    key_env: str = Field(default='RESEARCH_MODEL_KEY', pattern=r'^[A-Z][A-Z0-9_]{0,80}$')
    consent: bool = False
    vision: bool = False
    max_calls: int = Field(default=10, ge=1, le=1000)
    max_tokens: int = Field(default=4096, ge=256, le=16000)
    max_cost: float = Field(default=1, gt=0, le=10000)
    input_per_million: float = Field(default=0, ge=0)
    output_per_million: float = Field(default=0, ge=0)


class ReportRequest(Strict):
    kind: Literal['paper', 'experiment', 'weekly']
    title: str = Field(min_length=1, max_length=160)
    sources: list[str] = Field(default_factory=list, max_length=100)
    style: Literal['academic', 'paper', 'lab']
    mode: Literal['scroll', 'deck'] = 'scroll'
    start: datetime | None = None
    end: datetime | None = None
    include_final: bool = False
    start_day: date | None = None
    end_day: date | None = None

    @model_validator(mode='after')
    def period(self):
        if self.kind == 'weekly':
            if self.start_day is not None or self.end_day is not None:
                if not self.start_day or not self.end_day or self.start_day > self.end_day:
                    raise ValueError('请选择有效的开始与结束日期')
                return self
            if not self.start or not self.end or not self.start.tzinfo or not self.end.tzinfo:
                raise ValueError('周报须指定带时区的起止时间')
            if self.start >= self.end:
                raise ValueError('结束时间必须晚于开始时间')
        return self
