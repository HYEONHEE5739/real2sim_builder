"""One current scene, atomic state, append-only history and isolated project assets."""
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
import yaml

STAGES = ['ANALYZE', 'CAMERA & SCALE', 'GEOMETRY', 'VISUAL', 'PHYSICS', 'VALIDATION', 'EXPORT']
STATUSES = {'DRAFT','RUNNING','PAUSED','STOPPED','ACCEPTED','NEEDS_MORE_DATA','FAILED'}


def read(path):
    with Path(path).open() as stream: return yaml.safe_load(stream)


def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('w') as stream:
            if path.suffix == '.json': json.dump(data, stream, indent=2, allow_nan=False)
            else: yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=True)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally: temp.unlink(missing_ok=True)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): digest.update(block)
    return digest.hexdigest()


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.info = read(self.root / 'project.yaml')

    @classmethod
    def create(cls, projects, name):
        if not name.strip(): raise ValueError('Scene name required')
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'scene'
        root = Path(projects).resolve() / (slug + '-' + uuid.uuid4().hex[:8])
        root.mkdir(parents=True, exist_ok=False)
        for child in ('input', 'input/assets', 'working', 'scratch', 'exports'): (root/child).mkdir()
        write(root/'project.yaml', {'schema':'real2sim.project/1','id':root.name,'name':name,'created_at':time.time()})
        write(root/'input/evidence.yaml', {'images':[],'videos':[],'landmarks':[],'masks':[],'motions':[]})
        write(root/'working/state.json', {'status':'DRAFT','stage':None,'iteration':0,'decision':'CONTINUE','metrics':{},'needs':[]})
        return cls(root)

    @property
    def evidence(self): return read(self.root/'input/evidence.yaml')
    @property
    def state(self): return read(self.root/'working/state.json')
    @property
    def scene(self): return read(self.root/'working/current_scene.yaml')

    def update(self, **fields):
        state = {**self.state, **fields, 'updated_at':time.time()}
        if state['status'] not in STATUSES: raise ValueError('Invalid run status')
        write(self.root/'working/state.json', state)
        with (self.root/'history.jsonl').open('a') as stream: stream.write(json.dumps(state, allow_nan=False)+'\n')
        return state

    def control(self, command):
        if command not in ('pause','resume','stop'): raise ValueError('Unknown command')
        write(self.root/'working/control.json', {'command':command})

    def invalidate(self):
        if self.state['status'] not in ('DRAFT','RUNNING','PAUSED'):
            self.update(status='DRAFT',stage=None,decision='CONTINUE',needs=[],export=None,error=None,
                task='Inputs changed; validation must be rerun')

    def signature(self, scene=None):
        """Bind a validation decision to the exact scene and local evidence bytes."""
        from app.core.scene import local_path
        scene = scene if scene is not None else self.scene
        evidence = self.evidence
        files = {}
        def collect(node):
            if isinstance(node, dict):
                for key, item in node.items():
                    if key in ('path','mask') and isinstance(item, str):
                        files[item] = sha(local_path(self.root,item))
                    else: collect(item)
            elif isinstance(node, list):
                for item in node: collect(item)
        collect(evidence);collect(scene['assets'])
        def digest(data):return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()
        return {'scene_sha256':digest(scene),'evidence_sha256':digest(evidence),'files':files}

    def checkpoint(self):
        command = self.root/'working/control.json'
        if not command.exists(): return
        instruction = read(command)['command']
        command.unlink()
        if instruction == 'stop': raise InterruptedError('User stopped reconstruction')
        if instruction == 'pause':
            self.update(status='PAUSED')
            while True:
                time.sleep(.1)
                if not command.exists(): continue
                instruction = read(command)['command']; command.unlink()
                if instruction == 'stop': raise InterruptedError('User stopped reconstruction')
                if instruction == 'resume': break
            self.update(status='RUNNING')

    def save_scene(self, scene):
        write(self.root/'working/current_scene.yaml', scene)
        self.invalidate()
