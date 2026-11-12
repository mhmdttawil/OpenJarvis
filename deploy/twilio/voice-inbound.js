// Twilio Function: lets you CALL Jarvis and talk to it.
// Deploy in Twilio Console > Functions & Assets > Services > create "jarvis-voice",
// add this as a Function at path /voice (Public), set the Environment Variables
// JARVIS_URL (https://<service>.onrender.com) and JARVIS_API_KEY (the OPENJARVIS_API_KEY
// from Render), add the "axios" dependency, Deploy All, then point your Twilio
// number's Voice > "A call comes in" webhook at the Function URL.
//
// Flow: greet -> listen (speech-to-text) -> POST transcript to Jarvis /v1/chat/completions
// (the server's orchestrator agent, so ops_portal etc. are available) -> speak the answer
// -> listen again. Conversation history rides along in a Twilio cookie (last 6 turns).

const axios = require('axios');

const VOICE = 'Polly.Matthew';
const MAX_TURNS = 6;

exports.handler = async function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();
  const res = new Twilio.Response();
  res.appendHeader('Content-Type', 'text/xml');

  // Only answer the owner's phone.
  const owner = (context.JARVIS_OWNER_PHONE || '').trim();
  const caller = (event.From || event.To || '').trim(); // From on inbound; To on an outbound call we placed
  if (owner && caller !== owner && event.Direction !== 'outbound-api') {
    twiml.say({ voice: VOICE }, 'Sorry, this line is private.');
    twiml.hangup();
    res.setBody(twiml.toString());
    return callback(null, res);
  }

  let history = [];
  try { history = JSON.parse((event.request.cookies || {}).hist || '[]'); } catch (_) {}

  const heard = (event.SpeechResult || '').trim();

  if (!heard) {
    // First leg (or nothing heard): greet and listen.
    const g = twiml.gather({ input: 'speech', action: '/voice', method: 'POST', speechTimeout: 'auto', language: 'en-US' });
    g.say({ voice: VOICE }, history.length ? 'Go ahead.' : 'Jarvis here. How can I help?');
    twiml.say({ voice: VOICE }, 'I did not catch that. Goodbye.');
    res.setBody(twiml.toString());
    res.setCookie('hist', JSON.stringify(history), ['Path=/']);
    return callback(null, res);
  }

  if (/^(bye|goodbye|that'?s all|nothing else|hang up)\b/i.test(heard)) {
    twiml.say({ voice: VOICE }, 'Talk soon. Goodbye.');
    twiml.hangup();
    res.setBody(twiml.toString());
    return callback(null, res);
  }

  history.push({ role: 'user', content: heard });
  let answer = 'Sorry, I could not reach the server.';
  try {
    const r = await axios.post(
      `${context.JARVIS_URL}/v1/chat/completions`,
      {
        model: 'claude-sonnet-4-6',
        messages: [
          { role: 'system', content: 'You are Jarvis on a phone call with the owner of Stonepoint Property Services. Answer in one or two short spoken sentences. No lists, no symbols, no phone numbers or codes. Use the ops_portal tool when asked about jobs, invoices, payments, balance or expenses.' },
          ...history.slice(-MAX_TURNS * 2),
        ],
        max_tokens: 200,
      },
      { headers: { Authorization: `Bearer ${context.JARVIS_API_KEY}` }, timeout: 14000 }
    );
    answer = (r.data.choices?.[0]?.message?.content || '').replace(/[*_#`]/g, '').trim() || 'I have nothing on that.';
  } catch (e) {
    console.error(e.message);
    answer = 'That took too long. Ask me again, or text me and I will reply.';
  }
  history.push({ role: 'assistant', content: answer.slice(0, 400) });

  const g = twiml.gather({ input: 'speech', action: '/voice', method: 'POST', speechTimeout: 'auto', language: 'en-US' });
  g.say({ voice: VOICE }, answer);
  twiml.say({ voice: VOICE }, 'Goodbye.');
  res.setBody(twiml.toString());
  res.setCookie('hist', JSON.stringify(history.slice(-MAX_TURNS * 2)).slice(0, 3500), ['Path=/']);
  return callback(null, res);
};
