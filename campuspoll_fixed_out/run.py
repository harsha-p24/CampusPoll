from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    # allow_unsafe_werkzeug=True is required in debug mode with newer Werkzeug (3.x).
    # Without it, flask-socketio cannot attach its internal server object, causing
    # AttributeError: 'NoneType' object has no attribute 'eio'.
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
