"""Durable logical-call limits and one shared retry across all document stages."""
from .common import Issue, StageFailure, atomic_json, digest, fail, read_json

LIMITS = {'plan': 1, 'draft': 1, 'repair': 1, 'expand': 2, 'review': 1}


class BoundedClient:
    def __init__(self, client, config, store):
        self.inner, self.config, self.store = client, config, store

    def state(self, candidate):
        path = self.store.run_dir/'candidates'/candidate/'call_policy.json'
        return path, read_json(path) if path.exists() else {'requests':0,'retries':0,'operations':{}}

    def count(self, candidate, task):
        return sum(o['task']==task for o in self.state(candidate)[1]['operations'].values())

    def request(self, candidate, stage, task, system, payload, schema):
        return self.validated_request(candidate,stage,task,system,payload,schema,lambda value:value)

    def validated_request(self, candidate, stage, task, system, payload, schema, validator):
        key=digest([stage,task,system,payload,schema])
        path,state=self.state(candidate)
        result_path=path.parent/'bounded_responses'/(key+'.json')
        operation=state['operations'].get(key)
        if operation and operation['status']=='completed':
            result=read_json(result_path)
            if digest(result)!=operation['result_hash']:
                fail('BOUNDED_CACHE_HASH','Cached validated response changed','CODE_FIX',True)
            return result
        if operation is None:
            if self.count(candidate,task)>=LIMITS[task]:
                fail('STAGE_CALL_LIMIT',f'{task}: logical request limit {LIMITS[task]} reached','STOP_CANDIDATE')
            operation={'task':task,'attempts':0,'status':'pending'}
            state['operations'][key]=operation
            atomic_json(path,state)
        if operation['status']=='failed':
            raise StageFailure([Issue(**i) for i in operation['issues']])
        while True:
            if state['requests']>=min(7,self.config['max_provider_requests_per_candidate']):
                previous=[Issue(**i) for i in operation.get('issues',[])]
                raise StageFailure(previous+[Issue('CANDIDATE_CALL_LIMIT','Shared document request cap reached','STOP_CANDIDATE')])
            if operation['attempts']:
                if state['retries']>=1:
                    fail('SHARED_RETRY_LIMIT','The document has already used its single retry','STOP_CANDIDATE')
                state['retries']+=1
                self.store.event(candidate,stage,'bounded_retry',{'task':task,'operation':key})
            operation['attempts']+=1
            state['requests']+=1
            atomic_json(path,state)  # Reservations survive interruption/restart.
            request_payload=dict(payload)
            if operation.get('issues'):
                request_payload['response_feedback']=operation['issues']
            try:
                result=validator(self.inner.request(candidate,stage,task,system,request_payload,schema))
                atomic_json(result_path,result,private=True)
                operation.update(status='completed',result_hash=digest(result))
                atomic_json(path,state)
                return result
            except StageFailure as exc:
                invalid_review=getattr(exc,'review_response',None)
                if invalid_review is not None:
                    version=self.store.db.execute('SELECT COUNT(*)+1 FROM reviews WHERE candidate_id=?',(candidate,)).fetchone()[0]
                    quality=invalid_review.get('quality',{})
                    if isinstance(quality,dict) and isinstance(quality.get('scores',{}),dict):
                        self.store.grade(candidate,version,invalid_review,False,False,False)
                    self.store.save_artifact(candidate,f'review_versions/invalid_review_v{version}.json',invalid_review)
                    del exc.review_response  # Runner must not count the same response again.
                operation['issues']=[i.json() for i in exc.issues]
                retryable=not exc.fatal and all(i.action=='RETRY_RESPONSE' for i in exc.issues)
                if not retryable or state['retries']>=1 or state['requests']>=min(7,self.config['max_provider_requests_per_candidate']):
                    operation['status']='failed'
                    atomic_json(path,state)
                    raise
                atomic_json(path,state)


def validated_request(client, candidate, stage, task, system, payload, schema, validator):
    if isinstance(client,BoundedClient):
        return client.validated_request(candidate,stage,task,system,payload,schema,validator)
    return validator(client.request(candidate,stage,task,system,payload,schema))
