/**
 * frontend/js/context.js
 * Tracks conversation context so follow-up questions work.
 * e.g. "სად ტარდება?" after a concert list → prepends last event name.
 */

let _lastVenue  = '';
let _lastPlace  = '';
let _lastEvent  = '';
let _lastDate   = '';

// Bare spatial references (no specific name given)
const _REF_WORDS = /^(მანდ|იქ|იქამდე|მანდამდე|ამ\s+ადგილ|ამ\s+თეატრ|ამ\s+სპექტაკლ|იმ\s+ადგილ|ჩავიდე\s+მანდ|წამიყვანე\s+მანდ|წამიყვანე\s+იქ|მიმიყვანე\s+მანდ|მიმიყვანე\s+იქ)/i;
const _JOURNEY_REF = /(წამიყვანე|მიმიყვანე|ჩაიყვანე|გზა\s+მანდ|მარშრუტი\s+მანდ)/i;

// Event follow-up: no named event in query, short question about what was just mentioned
const _EVENT_FOLLOWUP = /^(და\s+)?(სად\s+(ტარდება|იმართება|არის|გაიმართება)|მითხარი\s+მეტი|დეტალები|აღწერა|შესახებ)/i;
// These include a date question but NO specific event name — only apply context if no Georgian noun
const _DATE_FOLLOWUP  = /^(და\s+)?(როდის\s+(ტარდება|არის|იმართება|გაიმართება|იქნება)|რა\s+დღეებ|სეანსები)/i;

export function update(userText, responseText, queryData) {
  const lower = userText.toLowerCase();

  // Date tracking
  if (/ხვალ|tomorrow|ხვალინდელ/.test(lower))     _lastDate = 'ხვალ';
  else if (/დღეს|today/.test(lower))              _lastDate = 'დღეს';
  else if (/ზეგ/.test(lower))                      _lastDate = 'ზეგ';
  else if (/ამ კვირ|this week/.test(lower))        _lastDate = 'ამ კვირაში';
  const dm = userText.match(/(\d{1,2})\s*(იან|თებ|მარ|აპრ|მაი|ივნ|ივლ|აგვ|სექ|ოქტ|ნოე|დეკ)/);
  if (dm) _lastDate = `${dm[1]} ${dm[2]}`;

  // Venue from response text
  const vm = responseText.match(/([ა-ჿ\s]{4,}(?:თეატრ\w*|42|სივრც\w*|მუზეუმ\w*|პარკ\w*))/i);
  if (vm) _lastVenue = vm[1].trim();

  // From API results
  if (queryData?.results?.length) {
    const first = queryData.results[0];
    if (first.venue && first.venue !== 'N/A') _lastVenue = first.venue;
    if (first.name)                           _lastEvent = first.name;
  }

  // Place from journey response
  const pm = responseText.match(/^([ა-ჿ\s]{3,20})(?:ში|ამდე|თან)\s+მისასვლელ/);
  if (pm) _lastPlace = pm[1].trim();
}

export function getLastDate() {
  return _lastDate;
}

export function enrich(text, savedHome) {
  const lower = text.toLowerCase();
  const trimmed = text.trim();

  // "from X to home" — replace home word with saved address
  if (savedHome?.address) {
    const toHomePatterns = [/სახლამდე/, /სახლში\s+მივი/, /სახლისკენ/];
    if (toHomePatterns.some(p => p.test(lower)) && /იდან|მეტრო|სადგურ|გაჩერება/.test(lower)) {
      return text.replace(
        /სახლამდე|სახლში\s+მივი\w*|სახლისკენ/g,
        savedHome.address + '-ამდე',
      );
    }
  }

  // Check if the query already contains a specific Georgian noun (event name, place)
  // If it does — don't inject context, user is asking about something specific
  const hasSpecificNoun = /[\u10D0-\u10FF]{4,}(?:ი|ა|ე|ო|ს|ში|ზე|ად)\b/.test(text)
    && text.trim().split(/\s+/).length > 2;

  // Event follow-up WITHOUT a named event — e.g. "სად ტარდება?" after a list
  if (_EVENT_FOLLOWUP.test(trimmed) && _lastEvent && !hasSpecificNoun) {
    return `${_lastEvent} ${text}`;
  }
  // Date follow-up WITHOUT named event
  if (_DATE_FOLLOWUP.test(trimmed) && _lastEvent && !hasSpecificNoun) {
    return `${_lastEvent} ${text}`;
  }

  // Bare spatial reference → inject last known place/venue
  const isBareRef    = _REF_WORDS.test(trimmed);
  const isJourneyRef = _JOURNEY_REF.test(text) && !text.includes('სახლ');
  const hasNoPlace   = !/[ა-ჿ]{5,}(?:ში|ამდე|ზე|თან)\b/.test(text);
  if ((isBareRef || (isJourneyRef && hasNoPlace)) && (_lastVenue || _lastPlace || _lastEvent)) {
    const ctx = _lastVenue || _lastPlace || _lastEvent;
    return `${text} (${ctx}-ში)`;
  }

  return text;
}

export function reset() {
  _lastVenue = ''; _lastPlace = ''; _lastEvent = ''; _lastDate = '';
}