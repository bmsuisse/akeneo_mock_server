const { PGlite } = require('@electric-sql/pglite');
const { PGLiteSocketServer } = require('@electric-sql/pglite-socket');
const fs = require('fs');
const path = require('path');


async function startServer() {
    try {
        // Create a PGlite instance with extensions
        const db = new PGlite({
            extensions: {}
        });

        // Create and start a TCP server
        const server = new PGLiteSocketServer({
            db,
            host: '127.0.0.1',
            port: 15432
        });
        await server.start();
        console.log(`Server started on TCP 127.0.0.1:15432`);

        // Handle graceful shutdown
        process.on('SIGINT', async () => {
            console.log('Received SIGINT, shutting down gracefully...');
            try {
                await server.stop();
                await db.close();
                console.log('Server stopped and database closed');
            } catch (err) {
                console.error('Error during shutdown:', err);
            }
            process.exit(0);
        });

        process.on('SIGTERM', async () => {
            console.log('Received SIGTERM, shutting down gracefully...');
            try {
                await server.stop();
                await db.close();
                console.log('Server stopped and database closed');
            } catch (err) {
                console.error('Error during shutdown:', err);
            }
            process.exit(0);
        });

        // Keep the process alive
        process.on('exit', () => {
            console.log('Process exiting...');
        });

    } catch (err) {
        console.error('Failed to start PGlite server:', err);
        process.exit(1);
    }
}

startServer();