const crypto = require('crypto');
if (!globalThis.crypto) globalThis.crypto = crypto.webcrypto || crypto;
if (!global.crypto) global.crypto = crypto.webcrypto || crypto;

const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, Browsers } = require('@whiskeysockets/baileys');
const path = require('path');
const fs = require('fs');
const pino = require('pino');

async function test() {
    const authDir = path.resolve(__dirname, 'auth_test');
    if (fs.existsSync(authDir)) fs.rmSync(authDir, { recursive: true, force: true });
    fs.mkdirSync(authDir, { recursive: true });

    const { state, saveCreds } = await useMultiFileAuthState(authDir);

    const sock = makeWASocket({
        logger: pino({ level: 'info' }),
        printQRInTerminal: true,
        auth: state,
        browser: Browsers.macOS('Desktop'),
        connectTimeoutMs: 60000,
        syncFullHistory: false
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (qr) {
            console.log('>>> SUCCESS! QR GENERATED <<<');
            console.log('QR String length:', qr.length);
            process.exit(0);
        }
        if (connection === 'close') {
            console.log('Connection closed:', lastDisconnect?.error?.message || lastDisconnect?.error);
        }
    });
}

test().catch(console.error);
