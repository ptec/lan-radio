const STATUS_PENDING      = "pending"
const STATUS_APPROVED     = "approved"
const STATUS_NOT_APPROVED = "not-approved"

const COLUMN_TITLE      = 1
const COLUMN_ARTIST     = 2
const COLUMN_YOUTUBE_ID = 3
const COLUMN_STATUS     = 4
const COLUMN_NOTES      = 5

const STATUS = [
  STATUS_PENDING ,
  STATUS_APPROVED,
  STATUS_NOT_APPROVED
]

// GET
const ACTION_GET_STATIONS = "getStations"
const ACTION_GET_STATION  = "getStation"

// POST
const ACTION_CREATE_STATION = "createStation"
const ACTION_UPDATE_STATION = "updateStation"

function doGet(e) {
  try {
    const q = JSON.parse(e.parameter.q)

    switch (q.action) {
      case ACTION_GET_STATIONS: return getStations(q);
      case ACTION_GET_STATION : return getStation (q);
    }

    throw new Error(`[doGet] Endpoint for action '${q.action}' is not defined.`);
  } catch (e) {
    return error(e.message)
  }
}

function doPost(e) {
  try {
    const q = JSON.parse(e.parameter.q)

    switch (q.action) {
      case ACTION_CREATE_STATION: return createStation(q);
      case ACTION_UPDATE_STATION: return updateStation(q);
    }

    throw new Error(`[doPost] Endpoint for action '${q.action}' is not defined.`);

  } catch(e) {
    return error(e.message)
  }
}

function getStations(q) {
  const sheets = SpreadsheetApp.getActiveSpreadsheet().getSheets()
  const ids    = sheets.map(sheet => sheet.getName())
  return ok(ids)
}

function getStation ({
  stationId
}) {
  if (typeof stationId !== "string")
    throw new Error(`[getStation] Type of stationId is '${typeof stationId}', expected 'string'.`)

    const sheet = getSheet(stationId)

    if (!sheet)
      throw new Error(`[getStation] Station with id '${stationId}' does not exist.`)

    const rows    = sheet.getDataRange().getValues()
    const headers = rows.shift() // throw away headers
    const entries = rows.map(row => ({
      title    : String(row[COLUMN_TITLE      - 1] ?? '').trim(),
      artist   : String(row[COLUMN_ARTIST     - 1] ?? '').trim(),
      youtubeId: String(row[COLUMN_YOUTUBE_ID - 1] ?? '').trim(),
      status   : String(row[COLUMN_STATUS     - 1] ?? '').trim(),
      notes    : String(row[COLUMN_NOTES      - 1] ?? '').trim()
    }))

    return ok(entries)
}

function createStation({
  stationId
}) {
  if (typeof stationId !== "string")
    throw new Error(`[createStation] Expected 'stationName' to be of type 'string', received '${typeof stationId}' instead.`)

  if(getSheet(stationId))
    throw new Error(`[createStation] Station with id '${stationId}' already exists.`)

  const sheet = newSheet(stationId)

  sheet.appendRow([
    "Title" ,
    "Artist",
    "YouTube Id",
    "Status",
    "Notes" ,
  ])

  return getStations()
}

function updateStation({
  stationId,
  state
}) {
  if (typeof stationId !== "string")
    throw new Error(`[updateStation] Expected 'stationId' to be of type 'string', received '${typeof stationId}' instead.`)

  if (!state || typeof state !== "object" || Array.isArray(state))
    throw new Error(`[updateStation] Expected 'state' to be of type 'object', received '${typeof state}' instead.`)

  const sheet = getSheet(stationId)

  if (!sheet)
    throw new Error(`[updateStation] Station with id '${stationId}' does not exist.`)

  const rows    = sheet.getDataRange().getValues()
  const headers = rows.shift()
  const entries = rows.map(row => ({
    title    : String(row[COLUMN_TITLE      - 1] ?? '').trim(),
    artist   : String(row[COLUMN_ARTIST     - 1] ?? '').trim(),
    youtubeId: String(row[COLUMN_YOUTUBE_ID - 1] ?? '').trim(),
    status   : String(row[COLUMN_STATUS     - 1] ?? '').trim(),
    notes    : String(row[COLUMN_NOTES      - 1] ?? '').trim()
  }))

  function keyOf({title, artist}) {
    return `${title}:${artist}`
  }

  for (const [key, value] of Object.entries(state)) {
    let {title, artist, youtubeId, status, notes} = value

    // normalize fields
    if (title    ) title     = String(title    ).trim()
    if (artist   ) artist    = String(artist   ).trim()
    if (youtubeId) youtubeId = String(youtubeId).trim()
    if (status   ) status    = String(status   ).trim()
    if (notes    ) notes     = String(notes    ).trim()

    const row   = entries.findIndex(e => key === keyOf(e))
    const entry = entries[row]

    if (row >= 0) {
      // merge existing

      // try modify title/artist
      if (
        (title  && title  !== entry.title ) ||
        (artist && artist !== entry.artist)
      ) {
        const newKey = keyOf({
          title : title  || entry.title ,
          artist: artist || entry.artist
        })

        // rename only if there is no collision
        if(!entries.find(e => newKey === keyOf(e))) {
          if (title ) {
            // update the in-memory map
            entry.title = title;
            // update the sheet
            sheet.getRange(row + 2, COLUMN_TITLE ).setValue("'" + title)
          }

          if (artist) {
            // update the in-memory map
            entry.artist = artist;
            // update the sheet
            sheet.getRange(row + 2, COLUMN_ARTIST).setValue("'" + artist)
          }
        }
      }

      // update the youtubeId if it differs
      if (youtubeId !== undefined && youtubeId !== entry.youtubeId) {
        // update the in-memory map
        entry.youtubeId = youtubeId;
        // update the sheet
        sheet.getRange(row + 2, COLUMN_YOUTUBE_ID).setValue("'" + youtubeId)
      }

      // update the status if it differs
      if (STATUS.includes(status) && status !== entry.status) {
        // update the in-memory map
        entry.status = status;
        // update the sheet
        sheet.getRange(row + 2, COLUMN_STATUS).setValue(status)
      }

      // update the notes if it differs
      if (notes !== undefined && notes !== entry.notes) {
        // update the in-memory map
        entry.notes = notes;
        // update the sheet
        sheet.getRange(row + 2, COLUMN_NOTES).setValue("'" + notes)
      }
    } else        {
      // create new

      title     = title     || ""
      artist    = artist    || ""
      youtubeId = youtubeId || ""
      status    = status    || STATUS_PENDING
      notes     = notes     || ""

      const newKey = keyOf({title, artist})

      // append entry only if there is no collision
      if(!entries.find(e => newKey === keyOf(e))) {
        // update the in-memory map
        entries.push({title, artist, youtubeId, status, notes})
        // update the sheet
        sheet.appendRow(["'" + title, "'" + artist, "'" + youtubeId, status, "'" + notes])
      }
    }
  }

  return ok(entries)
}

function newSheet(name) {
  const  sheet = SpreadsheetApp.getActiveSpreadsheet().insertSheet(name)
  return sheet
}

function getSheet(name) {
  const  sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name)
  return sheet
}

function ok(content) {
  return ContentService.createTextOutput()
    .setContent (JSON.stringify({
      ok: true, content
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

function error(error) {
  return ContentService.createTextOutput()
    .setContent(JSON.stringify({
      ok: false, error
    }))
    .setMimeType(ContentService.MimeType.JSON);
}
