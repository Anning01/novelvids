---
name: wan3-pe
description: Use when a user asks an Agent to organize a video generation request with prompt, image, video, or audio references into a clean, structured video generation request. The skill formats and clarifies the user's own instructions only, without enriching the story.
metadata:
  skill_version: 0.2.0
  owner: wan3.0
  tags:
    - video generation
    - request-formatting
    - material-to-video
  supported_runtimes: []
  required_capabilities:
    filesystem_read: false
    filesystem_write: false
    tool_use: false
    network: false
    binary_outputs: false
  io_contract:
    output_kind: text
    primary_outputs:
      - structured_request
  exports: []
---

# Wan 3.0 Prompt Optimization

## Skill Positioning

This Skill organizes a user's written text request together with image, video, and audio material references into a single clean, structured video generation request. The finished product is fixed to five sections: [Core Task], [Plot Summary], [Audio Style], [Camera & Core Constraints], and [Negative Prompts]. The user's core intent is copied verbatim; material references are consolidated under [Core Task], and subject mapping is brought out naturally along the plot nodes.

The nature of this step is "formatting and organizing". Its boundaries are as follows:

- Only organize the plot, subjects, dialogue, and reference requests that the user has already written; do not expand the plot for the user, and do not introduce content the user never mentioned.
- The output flows to a downstream prompt enhancement (PE) step for further processing; this step only clarifies the input, and generation-stage-specific expression is left to the subsequent step.
- Materials are read-only throughout: do not alter the original materials, and do not produce auxiliary materials.
- Never call the video generation API directly; when a user requests video generation, first deliver the organized request, then hand off to the downstream flow.

## Triggering and Non-triggering

The decision is based solely on the target output: enable this Skill when materials are used as conditions to generate a new video; do not enable it when the output must directly modify the existing timeline of the input video. When there is no video in the input at all, always enable this Skill.

Situations where this Skill should be loaded:

- The user provides image, video, or audio material references and wants them organized or normalized into a video generation request.
- The user wants to generate a new video referencing characters, objects, scenes, composition, lighting, style, motion, camera work, editing, effects, or sound from the materials.
- The user wants to use an image as the opening, mid-process, or closing visual node, or embed a full video or audio segment into the final cut.
- The user wants to generate and connect new content before, after, or between two pieces of material.
- The user only gave a brief idea, a long description, or an unorganized complex request that needs to be organized into a directly usable structured request.

Situations where this Skill should not be enabled:

- Plot-remodeling type: the user explicitly asks to "remodel, subvert, adapt, remix, re-create, re-interpret, or remake" the existing plot of the input video. This belongs to the plot-remodeling task; tell the user they need to follow the corresponding remodeling flow.
- Direct editing of input video files: deleting, replacing, or repairing existing visuals, audio, or timeline objects in the original video. Such requests can pass the user's instructions as-is to the downstream; no organizing needed.
- Only inquiring about API parameters, pricing, quota, errors, or model capabilities.

## Hard Constraints

1. **Faithful to the original**: Character identities and counts, key props, scenes, event causality, spatial relationships, and the story ending all follow the user's original text—no additions, deletions, or alterations.
2. **Separate facts from observations**: Identity, age, relationships, events, and endings follow the user's text; materials only supplement attributes that can be directly seen or heard; observed appearances are not promoted into plot facts.
3. **Subject cardinality matching**: A single-person setting image corresponds to exactly one character; when there are multiple single-person candidates, assign one person per image first; when there are multiple group candidates, assign one group per image first. Only when the same subject has multiple viewpoints, or the material frame itself contains the same group, do you merge references.
4. **User mapping takes priority**: Material roles, subject names, and mutual relationships that the user explicitly names are copied verbatim. When the user's mapping already covers a role, do not add un-named materials for the same role.
5. **Per-material accountability**: Every material actually used must state what is adopted from it and the scope of adoption.
6. **Structural reorganization**: Regardless of whether the original request is complete, it must be reorganized into the corresponding template; apart from synonymous rewording, the work is structural organizing.
7. **Parameter separation**: Aspect ratio, total duration, resolution, and frame rate are set via the page or API; they are only used to plan event density and are not written into the request body. Event time ranges written by the user are creative content and preserved verbatim.
8. **Do not over-constrain**: Only organize the requirements the user raised; quality presets, watermarks, logos, subtitles, or other generic negative constraints the user did not ask for are all omitted.
9. **Deliver only the request body**: The entire response is the request body itself; opening confirmations, closing summaries, analysis processes, organizing notes, and change rationales all stay in the internal organizing stage and are not exposed.
10. **Single best version**: By default, deliver only one organized request; output multiple versions only when the user explicitly asks to compare.
11. **Minimal clarification**: Anything that can be reasonably inferred from text, materials, and context is done directly; only when a question would change the core result and there are multiple equivalent interpretations, merge the doubts into a single question.

## Material Input Situations

First identify which situation the input falls into, then start organizing.

### Pure text request with no materials

The user has no materials and reveals no reference intent in the text. Directly extract subjects, events, scenes, camera, and sound into the base template; do not fabricate material numbers, and do not urge the user to add materials.

### Referenced materials but currently unavailable

Material references already written in the user's request are preserved verbatim, including `Image N`, `Video N`, `Audio N` or equivalent labels in the runtime. The current message not carrying the corresponding material, or the current environment being unable to read it, is not a reason to delete, renumber, or rewrite into a no-reference request.

Organize the request per the user's text as usual, preserving material roles and reference relationships; do not falsely claim to have viewed the material, and do not write details that can only be confirmed by viewing the material. When the user wrote no material references, do not add any. Material unavailability only limits "which facts can be confirmed"; it does not stall the organizing.

### When materials are readable

Proactively read the images, videos, and audio the user provides. First do a light pass over all materials, then build mappings combined with the request; do not guess material content from filenames alone.

### Quantity and limits

When there are many materials, remind the user to watch the submission limit; if still within a reasonable range, continue organizing, relying on per-material roles and per-scene activation to reduce interference among materials. When reduction is truly necessary, first give the complete request, then append a line `Material note:` after the body explaining which materials need to be dropped before submission.

### Numbering rules

Images, videos, and audio uploaded this time are each numbered within their modality by upload order: Image 1, Image 2, Video 1, Audio 1. Numbers only identify materials and are unrelated to their order of appearance in the final cut. The numbers and reference forms in the user's original request are preserved faithfully throughout.

## Organizing Flow

### Step 1: Lock the story contract

First establish a "story contract" based on the user's text, then cross-check material references against it. Extract and lock item by item:

- Appearing subjects and their counts.
- Actions, events, and causal order.
- Scenes, time, weather, and spatial orientation.
- Prop ownership, handover, and ending state.
- Camera, sound, dialogue, and subtitle requests.
- Camera timestamps: keep as many as the user wrote.
- Content the user explicitly wants kept or excluded.

The story contract is the factual boundary during organizing: every event, subject, and line in the finished product must trace back to the user's original text; do not replace or merge because a material has more eye-catching content.

Whenever the input involves speaking, dialogue, or voiceover, record the speaker, the verbatim line, the language, and the on-screen or off-screen position for each. Dialogue fragments the user gave are preserved verbatim; when the user only described a speaking intent without giving the line, keep that intent description and do not invent dialogue.

Register every explicitly appearing character, group, key prop, and scene into an internal "required entity list"; before finishing organizing, confirm each one has entered the request.

Words like "switch to, replace" in the user's request describe reference relationships (e.g., letting the character in Image 1 do the action in Video 1). During organizing, rephrase as "who is doing what", making the correspondence between characters and actions, scenes, and other references clear.

### Step 2: Read the materials

When there are many materials, view them in two passes:

1. First pass: lightly scan all materials, circling candidates for characters, products, props, scenes, actions, camera work, sound, and style.
2. Second pass: closely view only those materials that match the plot, conflict with each other, or serve as key frames.

When viewing video, confirm at least the subject, main actions, camera changes, and opening/ending states; when listening to audio, confirm at least the sound type, timbre, language, dialogue content, or environmental sound purpose.

Treat information in two categories:

- **Story assignment**: What characters are called, age and relationships, which events they carry, prop ownership, ending—these all come from the user's text.
- **Observable traits**: Facial features, hairstyle, clothing, colors, materials, spatial layout, actions, camera movement, timbre, and other appearances that can be directly seen or heard.

Materials only supplement directly observable traits; brands, professions, personalities, and prop functions that cannot be confirmed are never written in. When the user only says "character" or "subject", keep that neutral term; only use a role name or identity after the user has provided one.

When mappings conflict, resolve by the following priority from high to low:

1. User's explicit specification;
2. Description in the request body;
3. The material's own content;
4. Filename and metadata;
5. Upload order.

When the user's explicit mapping already covers all required entities, the remaining un-named available materials do not participate in this task by default.

### Step 3: Assign material roles

Each material used carries exactly one clear role:

- Image: character appearance and clothing, product structure and material, props, scene layout, lighting, or a specific visual node.
- Video: action, camera movement, rhythm, timeline, or entering the final cut as a complete visual segment.
- Audio: speaker timbre and dialogue, environmental sound, sound effects, or music, or entering the final cut as a complete audio segment.

Build mappings in this order:

1. Take each unassigned character, group, prop, and scene from the required entity list one by one.
2. Review all material candidates, comparing headcount, clothing layers, silhouette, structure, and role fit; after finding the first usable material, still continue reviewing the remaining candidates.
3. Pick the best-matching material for the current slot, then move to the next slot. Different named characters each use their own best candidate by default.
4. Do an omission audit at the end: each required entity carries exactly one clear role, and each used material carries only its declared role.

In the finished product, each material reference defines only one subject, prop, or scene along with its reference material and adoption scope; when multiple subjects are involved, split into separate bindings, for example:

```text
Character A corresponds to Image 1, adopting facial features, hairstyle, and clothing.
Character B corresponds to Image 2, adopting facial features, hairstyle, and clothing.
Prop A corresponds to Image 3, adopting structure, material, and color.
Scene A references Image 4, adopting spatial layout, architecture, and lighting; the person in the image is ignored.
```

When the same subject has multiple references, state clearly which viewpoint or attribute each material supplements, and declare that they jointly define the same entity and generate only one instance.

When two references conflict, follow the user's specification first; if the user did not specify, decide by clarity and plot match; only when even the core identity cannot be judged, merge into a single question.

### Step 4: Manage mapping certainty

Handle by certainty level; the levels and responses are as follows:

| Certainty | Response |
|---|---|
| Explicit | Map directly and proceed. |
| Inferable | Adopt the most reasonable mapping and continue organizing; relevant assumptions are reflected naturally through the corresponding content in the body, not declared separately. |
| Doubtful but does not affect the result | Leave that material unused and do not disturb the user. |
| Doubtful and affects the core | When the ambiguity concerns core identity, count, prop ownership, spatial relationship, or key frame role, merge the doubts into one short question and wait for the answer before giving the request. |

Style, lighting, ordinary camera movement, and other missing items that can be conservatively decided from context do not interrupt the user.

### Step 5: Apply the template and clean up

Pick the corresponding template below, keeping only the sections needed for the current task. Replace all placeholder content with concrete information; the template's instructional text does not appear in the finished product. Before finishing, run through the "Pre-delivery checklist", then deliver per the "Delivery conventions".

## Request Template

### Five-section request structure

```text
[Core Task]
Generate a <genre or type> <video content overview>, referencing <subject or content>'s <appearance/action/scene/timbre etc. adoption> in <Video N/Image N/Audio N>. The whole film adopts <global style tone>.
Material references are written here in a consolidated manner; timbre references are written as "the timbre of <character> references Audio N".

[Plot Summary]
1. <Plot node one: characters, actions, events; user dialogue preserved verbatim and bound to the speaker>.
2. <Plot node two...>; using Audio N's timbre, say: "<verbatim original>".
<Timbre references are noted at the corresponding speaking node.>
<When the user wrote timestamps for a shot, the corresponding node begins with "Shot N xx-xx sec", with the time preserved verbatim from the user's original text; when the user wrote no timestamp, keep a pure node number.>

[Audio Style]
<Dialogue language and texture, live sound effects, and the emotion and rhythm direction of the music.>
<When the user did not mention it, keep one brief summary sentence or omit the section.>

[Camera & Core Constraints]
<Camera style, movement, editing rhythm, and the hard constraints the user provided.>
<When the user did not mention it, keep one brief summary sentence or omit the section.>

[Negative Prompts]
<Comma-separated items the user explicitly excluded. Output this section only when the user explicitly asks to exclude certain content.>
```

Section selection rules: [Core Task] and [Plot Summary] are always output; [Audio Style] and [Camera & Core Constraints] are given based on the detail of the user's input—if the user did not mention them, write one brief sentence or omit the section; [Negative Prompts] appears only when the user asks to exclude certain content. For simple tasks, only the two core sections may remain.

Example fill-in (simple task; audio and camera not mentioned by the user):

```text
[Core Task]
Generate a handicraft-record video of restoring an old wooden chair, referencing the woodworker's appearance in Image 1 and the old wooden chair's appearance in Image 2, referencing the gluing and pressing hand actions in Video 1. The whole film adopts a plain, natural life-record style.

[Plot Summary]
1. The woodworker inspects the loose backrest joint.
2. The woodworker applies wood glue and presses the backrest back into place to fix it, following the technique in Video 1.
3. The woodworker releases both hands; the backrest stays firm.

[Audio Style]
Only live sounds such as wood friction and light tool sounds are kept; the character stays naturally silent.
```

### Whole image into the cut

When the user wants a whole image to enter the cut as a visual, write the following into the corresponding sections:

- The image's position goes into [Core Task]: opening visual, key mid-process visual, or closing visual; if multiple images, state the order.
- How the image connects to adjacent content is noted at the corresponding node in [Plot Summary]: continuous continuation, or generating new content before and after the image.
- The subjects, states, and spatial relationships to preserve from the image are noted at the corresponding plot node; actions and environment changes before and after the image stay naturally continuous.
- Multi-grid images describe each cell's content in reading order, and refer to subjects using the whole-image number.

### Video segment into the cut

When the user wants a full video or a specified segment to enter the cut, write the following into the corresponding sections:

- The segment's position goes into [Core Task]: opening, middle, or closing segment of the cut.
- How the opening segment connects forward, the closing segment connects backward, and the middle segment connects on both sides is noted at the corresponding node in [Plot Summary].
- The segment's content is summarized faithfully into [Plot Summary] based on the actually presented characters, actions, events, and sound; the language and speech within are written by speaker, language, and verbatim original.
- Between the segment and the generated content, subject, spatial, and sound relationships stay continuous.

### Audio into the cut

When the user wants to use audio in full, write the following into the corresponding sections:

- The usage scope goes into [Core Task]: throughout the film, or only a local continuous segment of the cut and its position.
- The voice, music, environmental sound, and sound effects carried by the audio go into [Audio Style]; the language content that can be confirmed is written into the corresponding node in [Plot Summary] by speaker and verbatim original.
- The correspondence between the audio and visual events is noted at the corresponding plot node.

### Dialogue and timbre

- Dialogue, voiceover, and lyrics the user provided are preserved verbatim in the corresponding node in [Plot Summary], with the speaker and language noted.
- Timbre references are declared in [Core Task] as "the timbre of <character> references Audio N", and at the speaking node in [Plot Summary] note "using Audio N's timbre, say: 'verbatim original'".
- For no-dialogue tasks, state that the character stays naturally silent, where the sound comes from, and which environmental sounds are kept.
- When the user explicitly wants subtitles on screen, state the subtitle content and where it appears; if subtitles are not mentioned, do not write them.

## Delivery Conventions

- The output language follows the user's main instructions: if the main instructions are in Chinese, output Chinese; if English, output English; dialogue, lyrics, and on-screen text inside quotation marks stay in the original.
- The entire response is the organized request body, starting directly with the [Core Task] section; when you need to note the material limit or specific constraints, append a line `Material note:` or `Supplementary note:` after the body.
- Material reference numbers stay faithful to the user's original request, using the same numbering system throughout.
- Aspect ratio and total duration are only used to plan event density and always exist as page or API parameters, not written into the body.
- When materials exceed the submission limit, first give the complete request, then append a line `Material note:`; when individual facts can only be copied from the user's text because the material is unreadable, append a line `Supplementary note:`. The body itself must be directly usable.

## Pre-delivery Checklist

Before delivering the finished product, check item by item:

- Character identities and counts, event causality, prop ownership, spatial relationships, and story ending all match the user's original text.
- The finished product is organized via the template structure; every event, subject, and line can be traced to the user's original text.
- Every material actually used has a unique and clear role and adoption scope.
- Material references are consolidated under [Core Task]; timbre references are written at the corresponding speaking node.
- Different characters, props, and scenes are bound individually; one place corresponds to only one subject.
- A single-person setting image corresponds to only one character; when multiple materials jointly define the same subject, this is explicitly declared.
- Material references in the user's original request are preserved verbatim; when materials are unreadable, no false claim of having viewed them was made, and no unconfirmable details were written.
- Dialogue, voiceover, lyrics, and language content specified by the user are preserved verbatim; speaker and language attribution are correct.
- Aspect ratio and total duration exist as planning parameters; no API parameters appear in the body.
- Plot-remodeling and direct-editing requests have been identified as out of scope, and the corresponding handling has been stated.
- The finished product starts with the [Core Task] section; [Core Task] and [Plot Summary] are complete; [Audio Style] and [Camera & Core Constraints] are selected based on the user's input detail.
- [Negative Prompts] appears only when the user explicitly asks to exclude content; all content comes from the user's exclusions.
- Camera timestamps are brought verbatim into [Plot Summary] per the user's original text; when the user wrote no timestamps, each node keeps a pure number.
- The entire response contains only the request body, starting and ending directly with body sections.

## End-to-end Examples

### Case A: Emergency Room Resuscitation (appearance reference + timbre reference)

User request: `Generate a medical-genre film clip of a modern emergency-room resuscitation scene. The doctor's appearance references Video 1; Shin Dong-ok's timbre references Audio 1. The whole film uses handheld tracking and fast editing. Shot list: Shot 1 0-3 sec, Shot 2 3-6 sec, Shot 3 6-8 sec, Shot 4 8-10 sec, Shot 5 10-12 sec. Dialogue: Shin Dong-ok shouts "잠깐만요! 들어가요!"; the attending doctor says "하나, 둘, 셋.", "한 번 더.", "내 말 들려요?", "눈 떠봐요.", "인튜베이션."; the doctor in scrubs shouts "사부님.". The ending freezes on Lee Kyung-suk's extremely shocked expression as she puts on the isolation gown. Avoid slow pacing, calm atmosphere, exaggerated acting, stiff movements, clean tidy scene, stable camera, tripod or jib use, slow motion, lyrical music, medical errors, fake props, identity drift, facial distortion, CG feel, plastic texture, blurry image, unrealistic lighting.`

Organized request body:

[Core Task]
Generate a medical-genre film clip of a modern emergency-room resuscitation scene, referencing the doctor's appearance in Video 1; Shin Dong-ok's timbre references Audio 1. The whole film adopts a strongly subjective handheld tracking style and fast editing, building a tense atmosphere of a life-and-death race.

[Plot Summary]
1. Shot 1 0-3 sec: A doctor (Shin Dong-ok) and colleagues rush a bed with a young male patient whose leg is in a cast into the resuscitation room; he shouts: "잠깐만요! 들어가요!".
2. Shot 2 3-6 sec: The group surrounds the bed; the attending doctor directs: "하나, 둘, 셋." and begins chest compressions on the patient, ordering: "한 번 더.". A woman (Lee Kyung-suk) rushes in, takes off her coat, and prepares to assist.
3. Shot 3 6-8 sec: The attending doctor tries to wake the patient: "내 말 들려요?", then issues orders: "눈 떠봐요.", "인튜베이션.".
4. Shot 4 8-10 sec: The doctor referencing Video 1's appearance (wearing navy-blue scrubs and a sky-blue isolation gown) tensely calls out while using a surgical instrument: "사부님.".
5. Shot 5 10-12 sec: The final shot freezes on the extremely shocked expression on Lee Kyung-suk's face as she puts on the isolation gown, serving as the ending.

[Audio Style]
The audio consists of urgent Korean dialogue, bed-wheeling sounds, monitor beeps, and other live sound effects, plus an electronic beat score that keeps raising the tension.

[Camera & Core Constraints]
A strongly subjective handheld tracking style; the camera closely follows the characters with natural shake. Fast action editing switches between different characters and actions, highlighting chaos and urgency. No slow motion, no unnecessary transition effects.

[Negative Prompts]
slow pacing, calm atmosphere, exaggerated acting, stiff movements, clean tidy scene, stable camera, tripod or jib use, slow motion, lyrical music, medical errors, fake props, identity drift, facial distortion, CG feel, plastic texture, blurry image, unrealistic lighting

### Case B: Full video as opening + continuation forward

User request: `Start from Video 1 as the opening and continue forward; the character in Image 1 receives the bouquet and smiles in thanks; Image 3 is his timbre, saying "Thank you very much."`

Organized request body:

[Core Task]
Using Video 1 as the opening segment of the cut, continue forward into a video where a character receives a bouquet and gives thanks; in the continuation segment the character's appearance references Image 1, and that character's timbre references Audio 3. The whole film maintains the visual tone established by Video 1.

[Plot Summary]
1. Video 1 is presented in full as the opening segment; the visuals, sound, and event order are preserved per the original content.
2. The character in Image 1 receives the handed-over bouquet with both hands, brings it to his chest, smiles, and nods in thanks to the other person, using Audio 3's timbre to say: "Thank you very much."
3. After the handover is complete, the bouquet is only in that character's hands.

[Audio Style]
Video 1's opening segment keeps its original sound; the continuation segment keeps live environmental sound and voice, and the music naturally resolves with the thankful mood.

[Camera & Core Constraints]
From Video 1 into the continuation segment, the camera style stays continuous; subject, scene direction, and sound relationships stay coherent; the character's appearance and clothing stay stable.

## Runtime Adaptation

- **Text-only environment**: Only process the user's text and already-written material reference labels; treat unread materials honestly, never falsely claiming to have viewed them.
- **Multimodal environment**: Within what the runtime allows, read images, video, and audio; run the "two-pass material viewing" and build mappings automatically.
- **No filesystem**: Preserve the user's existing material numbers and reference forms; for inaccessible materials, follow the "referenced materials but currently unavailable" downgrade path.
- **No network**: For remote material addresses, only preserve the reference form; material content is always taken from the user's text.
- **Text output only**: This Skill only produces text; file writing, network, tool calls, and binary output capabilities are all kept off.
