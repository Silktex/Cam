HANDOFF CONTEXT
===============

USER REQUESTS (AS-IS)
---------------------
- ~/projects/camera_system/sony/Examples/example-v2-linux contains sony exmple for building camera controls. Compare with existing gphoto2. I want non blocking commands. For exmple if I change shutter speed, live view disconnects takes few seconds to connect. Research online for best method for non blocking commands for sony a7r3
- Can we do it with libgphoto2?
- yes

GOAL
----
Finish and verify the non-blocking camera-control restructure of camera_service.py: run the test suite inside the Docker container (where gphoto2 and pytest are installed) to confirm no regression, and optionally add a regression test that locks in "live view survives a setting change".

WORK COMPLETED
--------------
- Researched Sony A7R III non-blocking control: read the Sony libcameracontrolptp example-v2-linux sample (socc_ptp.h/.cpp, command.cpp/.h, serverclient.cpp, parser.h, and the .sh scripts) and ran two parallel librarian agents plus one explore agent for online research (Sony Camera Remote SDK, libgphoto2 internals, OSS projects open-camera-control and bookThing).
- Established that the old camera_service.py live-view loop did `except gp.GPhoto2Error: break`, turning a transient preview failure into a full stream teardown. Related Sony preview stalls are documented upstream, but the exact A7R III object ID and 1-3 second duration remain hardware observations to verify.
- Recommended and implemented the worker-thread + command-queue + frame-ring-buffer architecture, entirely on libgphoto2 (python-gphoto2), since Sony USB/PTP is single-session and not thread-safe.
- Reworked api/app/services/camera_service.py and its lifecycle integrations; handoff.md and regression tests were also added:
  - Single daemon worker thread is the sole owner of the gp.Camera object.
  - Command queue (queue.Queue) with concurrent.futures.Future results for connect, get_settings, set_setting, capture_image, capture_only, download_from_camera, trigger_autofocus.
  - Live-view frame production moved into the worker loop; frames published to a latest-frame-wins ring buffer guarded by a Condition.
  - start_live_view() is now a consumer generator that reads the ring buffer, decoupling production from the HTTP MJPEG stream.
  - set_setting no longer stops or disrupts live view; the worker preempts preview for the duration of one set_config transaction and resumes.
  - _maybe_produce_frame retries on transient GPhoto2Error instead of killing the stream.
  - self._lock is a state/lifecycle lock (guards _camera/_context/_connected/_model); camera cleanup is dispatched to the worker and is not performed externally after a timed-out join.
  - Public method signatures and return shapes are preserved. EventBus WebSocket sends are transferred onto the FastAPI event loop, and batch cancellation uses libgphoto2's cooperative context cancellation instead of cross-thread camera.exit().
- Verified the concurrency architecture by driving the real singleton with a stubbed gphoto2 + fake camera (in /tmp, since gphoto2 is not installed in this sandbox): frame production, non-blocking set_setting during streaming, stream survival after a setting change, and retry-on-transient-error all passed (removed the temp test afterward).

CURRENT STATE
-------------
- api/app/services/camera_service.py includes bounded command waits, deterministic queue shutdown, worker-owned cleanup, generation-based live-view ownership, and cooperative capture cancellation.
- Docker verification passes: 13 focused lifecycle tests and the full 210-test API suite. Five dependency/deprecation warnings remain unrelated to the camera lifecycle fix.
- The repo has substantial pre-existing uncommitted work unrelated to this session (autoexposure feature under api/app/services/exposure/, web image-processing components, autoexposure.md, various tests) that was already present; this session did not touch it.
- The actual project root is /home/posh/projects/camera_system (the agent shell cwd /home/posh/Desktop/camera_system contains only an empty .omo directory and no project files).

PENDING TASKS
-------------
- Run physical-camera validation for live-view setting changes and cancellation. Automated Docker verification is complete; focused tests are in api/tests/test_camera_concurrency.py and api/tests/test_event_bus_threading.py.
- Physical A7R III validation passed for connect, live-view frames, ISO 800 -> 1000 -> 800 while streaming, stream continuity, stop, disconnect/reconnect, autofocus, and one RAW capture. Cancellation during an actively blocked capture remains untested.
- Optional follow-up: warn/freeze handling for exposure-mode (not just parameter) changes, which stall 3-8s on A7R III and are best avoided during live view.

KEY FILES
---------
- api/app/services/camera_service.py - the non-blocking camera controller (worker thread + command queue + ring buffer)
- api/app/routers/liveview.py - consumes start_live_view() generator via StreamingResponse (MJPEG)
- api/app/routers/camera.py - consumes set_setting/get_settings/trigger_autofocus/connect/disconnect/troubleshoot
- api/app/services/batch_capture_service.py - consumes capture_image/set_setting and requests cooperative cancellation
- api/app/services/exposure/controller.py - consumes get_settings/set_setting via CameraExposureController
- api/app/config.py - PREVIEW_FPS and other settings
- api/app/services/event_bus.py - EventType/event_bus publish/settle used by camera_service
- sony/Examples/example-v2-linux - Sony reference sample used for research (libcameracontrolptp, persistent socket server pattern)

IMPORTANT DECISIONS
-------------------
- Keep libgphoto2 (python-gphoto2) rather than migrating to Sony Camera Remote SDK v1.x. The A7R III firmware freeze happens regardless of driver, and a C++ bridge is a large lift; the SDK is only a fallback if gphoto2's A7R III quirks (e.g. #1080 movie-mode segfault) bite.
- True parallel control + streaming is impossible on any library because Sony USB/PTP is single-session; "non-blocking" is achieved by serializing on one worker thread and interleaving commands between frames, not by adding a second control channel.
- The 1-3s freeze after shutter/ISO/aperture changes is accepted as firmware behavior; the deliverable is that the stream survives (client shows last frame), not that the freeze disappears.
- capture_image/capture_only still stop live view before capturing (unchanged behavior), but set_setting no longer does.

EXPLICIT CONSTRAINTS
--------------------
- None stated by the user for the implementation beyond the request itself. No commit was requested and none was made.

CONTEXT FOR CONTINUATION
------------------------
- The lifecycle fixes are covered by 13 durable fake-camera concurrency tests and a 210-test full Docker run. Physical A7R III validation also passed for live-view setting changes, reconnect, autofocus, and RAW capture; active-capture cancellation remains outstanding.
- To reproduce the manual verification, stub gphoto2 in sys.modules and inject a fake camera via the service's internal state setters, then drive start_live_view() and set_setting() — the four checks I ran (frame yield, set_setting during stream, stream alive after, retry on transient error) are the acceptance criteria.
- Batch cancellation no longer force-calls camera.exit() from the event-loop thread. It sets the libgphoto2 context cancellation flag; cancellation latency therefore depends on the active libgphoto2 call reaching a cancellation check.
