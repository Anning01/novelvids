"""Keep valid storyboard slots immutable while repairing individual slots."""

from pydantic import Field, SkipValidation, ValidationError, create_model

from services.storyboard.speech_tracks import SpeechContent
from services.storyboard.validation import validate_blocking_map, validate_skill_storyboard_timing, validate_storyboard_duration, prepare_skill_storyboard


class StoryboardCandidateValidator:
    def __init__(self, output_type, snapshot, language, duration_range, facts):
        self.output_type, self.snapshot, self.language = output_type, snapshot, language
        self.duration_range = duration_range
        self.shot_type = output_type.model_fields['shots'].annotation.__args__[0]
        repair_shot = create_model(self.shot_type.__name__ + 'Repair', __base__=self.shot_type,
            repair_of=(int | None, Field(default=None, description='Original failed shot number; repeat it when splitting that shot')))
        self.draft_type = create_model(output_type.__name__ + 'Candidate',
            shots=(list[SkipValidation[repair_shot]], Field(min_length=1, max_length=200)))
        self.groups, self.pending, self.speech = {}, {}, {}
        self.raw = {}
        self.preserve_speech = True
        self.source_facts = facts
        while isinstance(self.source_facts, dict) and 'original_input' in self.source_facts:
            self.source_facts = self.source_facts['original_input']
        seed = facts.get('storyboard_repair') if isinstance(facts, dict) else None
        if seed:
            self.preserve_speech = False
            for shot in output_type.model_validate(seed['candidate']).shots:
                self.groups[shot.sequence] = [shot]
                self.raw[shot.sequence] = [shot.model_dump(mode='json')]
            self.pending = {number: ['Creative requirement needs correction'] for number in seed['shot_sequences']}

    def restore(self, checkpoint):
        self.raw = {int(number): values for number, values in checkpoint['candidates'].items()}
        self.pending = {int(number): errors for number, errors in checkpoint['pending'].items()}
        self.groups = {number: [self.shot_type.model_validate(value) for value in values]
                       for number, values in self.raw.items() if number not in self.pending}
        for number, speech in checkpoint.get('speech', {}).items():
            validator = SpeechContent()
            validator.original_speech = {(field, speaker): text for field, speaker, text in speech}
            self.speech[int(number)] = validator

    def result(self):
        shots = [shot.model_copy(update={'sequence': index}) for index, shot in enumerate(
            (shot for number in sorted(self.groups) for shot in self.groups[number]), 1)]
        return self.output_type(shots=shots)

    def validate_group(self, number, shots):
        errors = []
        if self.preserve_speech and 'storyboard_contract' in self.snapshot.contents:
            validator = self.speech.setdefault(number, SpeechContent())
            try:
                validator.validate(shots)
            except ValueError as error:
                errors.append(str(error))
        for shot in shots:
            try:
                validate_storyboard_duration(shot, self.duration_range)
                if 'storyboard_contract' in self.snapshot.contents:
                    validate_skill_storyboard_timing(shot)
                    if (isinstance(self.source_facts, dict) and self.source_facts.get('source_scene_number')
                            and shot.blocking_map is None):
                        # Model placement runs after segment order is final.
                        shot = shot.model_copy(update={'duration_split_part': None})
                    validate_blocking_map(shot, self.snapshot)
                    if isinstance(self.source_facts, dict) and 'entities' in self.source_facts:
                        from schemas.scene import SceneEntity
                        from services.creation_agent.prompt_edits import validate_prompt_dependencies
                        from services.storyboard.strategies import storyboard_strategy_factory
                        entities = [SceneEntity.model_validate(item) for item in self.source_facts['entities']]
                        strategy = storyboard_strategy_factory.resolve(self.source_facts.get('strategy'))
                        prepared = prepare_skill_storyboard(self.output_type(shots=[shot]), self.snapshot, self.language, entities, strategy.key)
                        validate_prompt_dependencies(prepared.shots[0].prompt, entities)
            except ValueError as error:
                errors.append(str(error))
        return list(dict.fromkeys(errors))

    def merge(self, output):
        first = not self.raw
        updates, protocol_errors = {}, []
        for index, raw in enumerate(output.shots, 1):
            raw = raw.model_dump() if hasattr(raw, 'model_dump') else raw
            if not isinstance(raw, dict):
                raw = {'invalid_candidate': raw}
            number = index if first else raw.get('repair_of') or raw.get('sequence')
            if not isinstance(number, int) or isinstance(number, bool):
                protocol_errors.append('repair_of must be an original integer shot number')
                continue
            if not first and number not in self.pending:
                if len(self.raw) == 1 and len(self.pending) == 1 and not raw.get('repair_of'):
                    number = next(iter(self.pending))  # Old single-shot split responses.
                elif number in self.groups:
                    continue  # Never accept edits to an already valid slot.
                else:
                    protocol_errors.append('Return only failed shot numbers with repair_of set to the original number')
                    continue
            updates.setdefault(number, []).append({key: value for key, value in raw.items() if key != 'repair_of'})
        for number, values in updates.items():
            self.raw[number] = values
            try:
                shots = [self.shot_type.model_validate({**value, 'sequence': number}) for value in values]
                errors = self.validate_group(number, shots)
            except ValidationError as error:
                errors = [f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors(include_input=False)]
            if errors:
                self.pending[number] = errors
            else:
                self.groups[number] = shots
                self.pending.pop(number, None)
        accepted = [number for number in self.groups if number not in self.pending]
        checkpoint = {'accepted_shots': accepted, 'pending': self.pending, 'candidates': self.raw,
                      'protocol_errors': protocol_errors,
                      'speech': {number: [[field, speaker, text] for (field, speaker), text in validator.original_speech.items()]
                                 for number, validator in self.speech.items() if validator.original_speech is not None}}
        if self.pending or protocol_errors:
            return None, checkpoint
        return self.result(), checkpoint
