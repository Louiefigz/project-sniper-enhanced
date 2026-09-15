import {SelectionPlayback} from './playback.mjs';

const $ = selector => document.querySelector(selector);
const video = $('#video');
const player = $('#player');
const labels = ['All ideas', 'Strongest', 'Assembled', 'Rants', 'Conversation'];
let ideas = [], active = null, filter = 'All ideas';
let sourceUrl = 'review-proxy.mp4', sourcePoster = '', editedMode = false;

const time = seconds => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function updatePlayback({state, message, range, step, total}) {
  const states = {playing: 'Playing', loading: 'Loading', paused: 'Paused',
    blocked: 'Playback blocked', error: 'Playback error', stopped: 'Stopped',
    finished: 'Selection finished · choose another idea'};
  const passage = range && !editedMode ? ` · passage ${step + 1}/${total} · source ${time(range.start)}–${time(range.end)}` : '';
  $('#status').textContent = message || `${states[state]}${passage}`;
  $('#status').dataset.state = state;
  $('#resume').hidden = !range || !['paused', 'blocked', 'error'].includes(state);
  if (range) $('#quote').textContent = `${range.role} · ${range.speaker}\n${range.quote}`;
  for (const node of document.querySelectorAll('.selection-state')) {
    node.textContent = node.dataset.idea === active ? states[state] : '';
  }
}

const playback = new SelectionPlayback(video, updatePlayback);

function play(idea, ranges, edited = false) {
  editedMode = edited;
  const file = edited ? idea.edited.mediaUrl : sourceUrl;
  video.poster = edited ? idea.edited.posterUrl || '' : sourcePoster;
  video.setAttribute('aria-label', edited ? 'Edited Short' : 'Original source video');
  $('#media-kind').textContent = edited ? 'Edited Short · captions + finished audio' : 'Original footage · selection preview';
  active = idea.id;
  $('#now-title').textContent = idea.title;
  render();
  playback.start(ranges, file);
  // The narrow layout stacks the player above the cards: always reveal it.
  player.scrollIntoView({behavior: 'instant', block: 'start'});
  player.focus({preventScroll: true});
}

$('#stop').onclick = () => playback.stop();
$('#resume').onclick = () => playback.resume();
$('#reload-video').onclick = () => playback.reload();

function visible(idea) {
  return filter === 'All ideas'
    || filter === 'Strongest' && idea.priority === 'A'
    || filter === 'Assembled' && idea.ranges.length > 1
    || filter === 'Rants' && idea.tags?.includes('rant')
    || filter === 'Conversation' && idea.tags?.includes('conversation');
}

function rangeButtons(idea) {
  const container = element('div', undefined, 'ranges');
  idea.ranges.forEach((range, index) => {
    if (index) container.append(element('span', '→'));
    const button = element('button', `${time(range.start)}–${time(range.end)}`);
    button.onclick = () => play(idea, [range]);
    button.title = range.role;
    container.append(button);
  });
  return container;
}

function detailsFor(idea) {
  const details = element('details');
  details.append(element('summary', 'Opening, sequence and visual treatment'));
  const list = element('ol');
  for (const range of idea.ranges) {
    list.append(element('li', `${range.role} (${range.speaker}, ${time(range.start)}–${time(range.end)}): ${range.quote}`));
  }
  details.append(list, element('p', `Visual treatment: ${idea.visual}`));
  return details;
}

function cardFor(idea) {
  const card = element('article', undefined, `card${active === idea.id ? ' playing' : ''}`);
  card.id = idea.id;
  const top = element('div', undefined, 'topline');
  const duration = Math.round(idea.ranges.reduce((sum, r) => sum + r.end - r.start, 0));
  const timing = idea.edited ? `${idea.edited.duration.toFixed(1)}s edited · ${idea.ranges.length} source passages`
    : `${duration}s selected · ${idea.target} edit target`;
  top.append(element('span', idea.priority === 'A' ? 'Start here' : 'Also viable', 'badge'),
    element('span', idea.kind), element('span', timing));
  card.append(top, element('h2', idea.title), element('p', idea.why),
    rangeButtons(idea), element('p', idea.caution, 'note'));
  const actions = element('div', undefined, 'actions');
  const label = idea.edited ? 'Play edited Short' : idea.ranges.length > 1 ? 'Play assembled selection' : 'Play selection';
  const button = element('button', label, 'primary');
  button.setAttribute('aria-label', `${label}: ${idea.title}`);
  button.onclick = () => idea.edited
    ? play(idea, [{start: 0, end: idea.edited.duration, role: 'Edited Short', speaker: 'Original dialogue', quote: idea.visual}], true)
    : play(idea, idea.ranges);
  const state = element('p', '', 'selection-state');
  state.dataset.idea = idea.id;
  actions.append(button);
  if (idea.edited) {
    const original = element('button', 'Compare original passages');
    original.onclick = () => play(idea, idea.ranges);
    actions.append(original);
  }
  card.append(actions, state, detailsFor(idea));
  return card;
}

function render() {
  const shown = ideas.filter(visible);
  $('#count').textContent = `${shown.length} ${ideas.some(idea => idea.edited) ? 'edited Shorts · original passages available for comparison' : 'selections · titles are proposed packaging'}.`;
  $('#cards').replaceChildren(...shown.map(cardFor));
}

function addFilters() {
  for (const label of labels) {
    const button = element('button', label, label === filter ? 'active' : '');
    button.onclick = () => {
      filter = label;
      document.querySelectorAll('#filters button').forEach(node => node.classList.toggle('active', node === button));
      render();
    };
    $('#filters').append(button);
  }
}

function validateCandidates(data) {
  if (!Array.isArray(data.candidates)) throw Error('Missing candidate list.');
  const validRange = range => Number.isFinite(range.start) && Number.isFinite(range.end)
    && range.start >= 0 && range.end > range.start
    && (!data.sourceDurationSeconds || range.end <= data.sourceDurationSeconds);
  if (data.candidates.some(idea => idea.edited && (!Number.isFinite(idea.edited.duration) || idea.edited.duration <= 0 || !idea.edited.mediaUrl))) {
    throw Error('An edited Short is missing its video or duration.');
  }
  if (data.candidates.some(idea => !idea.ranges?.length || !idea.ranges.every(validRange))) {
    throw Error('A selection has invalid source times. Correct candidates.json before playback.');
  }
}

async function load() {
  try {
    const response = await fetch('candidates.json');
    if (!response.ok) throw Error('Could not load candidates.json.');
    const data = await response.json();
    validateCandidates(data);
    ideas = data.candidates;
    const review = data.review || {};
    document.title = review.title || 'Sniper · Clip review';
    $('#heading').textContent = review.heading || 'The Shorts inside this conversation';
    $('#intro').textContent = data.summary;
    $('#speaker-note').textContent = review.speakerNote || '';
    $('#speaker-note').hidden = !review.speakerNote;
    sourceUrl = review.mediaUrl || 'review-proxy.mp4';
    sourcePoster = review.posterUrl || '';
    video.src = sourceUrl;
    if (review.posterUrl) video.poster = review.posterUrl;
    if (review.notesUrl) $('#notes-link').href = review.notesUrl;
    if (review.transcriptUrl) $('#transcript-link').href = review.transcriptUrl;
    if (ideas[0]?.edited) {
      video.src = ideas[0].edited.mediaUrl;
      video.poster = ideas[0].edited.posterUrl || '';
      $('#media-kind').textContent = 'Edited Short · ready to play';
      $('#now-title').textContent = ideas[0].title;
      $('#quote').textContent = 'Use Play edited Short on a card. Compare original passages plays the source recording.';
    }
    addFilters();
    render();
  } catch (error) {
    $('#intro').textContent = error.message;
  }
}

load();
