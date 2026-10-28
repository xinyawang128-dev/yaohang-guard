"""The requested injection module. Session owns validated physical simulation state."""


def inject_event(session, event_type, value=None):
    """Apply closure / wind / sensor_failure without resetting position or resources.

    Pass an existing engine.Session, or use TaskStore to share it across processes.
    Only simulated task state is changed; no device or model API is called.
    """
    result = session.event(event_type, value)
    return {**result, 'task_id': session.id, 'state': session.state,
            'headwind_ms': session.config['headwind_ms'],
            'closed_edges': session.config['closed_edges'],
            'replans': session.replans, 'agh_verified': False}
