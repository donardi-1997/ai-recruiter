// eslint-disable-next-line no-unused-vars
import React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import api from "../api/client";
import { useSession } from "../context/SessionContext";


function courseProgress(course) {
  return Number.isFinite(course?.progress_percent) ? course.progress_percent : 0;
}


function isDirectVideo(url) {
  return /\.(mp4|webm|ogg)(\?|#|$)/i.test(String(url || ""));
}


function Training() {
  const { principal, hasPermission } = useSession();
  const canManage = hasPermission("training.manage");
  const canAssign = hasPermission("training.assign");
  const canViewResults = hasPermission("training.results.read");
  const canTakeQuiz = hasPermission("training.quiz.take");
  const firstName = principal?.profile?.first_name || "equipo";

  const [myAssignments, setMyAssignments] = useState([]);
  const [courses, setCourses] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [selectedCourse, setSelectedCourse] = useState(null);
  const [courseAssignments, setCourseAssignments] = useState([]);
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");
  const [employeeCourse, setEmployeeCourse] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [creatingCourse, setCreatingCourse] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploadingLessonId, setUploadingLessonId] = useState("");
  const [courseForm, setCourseForm] = useState({ title: "", description: "" });
  const [moduleForm, setModuleForm] = useState({ title: "", description: "" });
  const [lessonForms, setLessonForms] = useState({});
  const [assignEmployeeId, setAssignEmployeeId] = useState("");
  const [quizForm, setQuizForm] = useState({
    title: "Evaluación final",
    passing_score: "70",
  });
  const [questionForm, setQuestionForm] = useState({
    prompt: "",
    options: ["", "", "", ""],
    correct_option: "0",
  });
  const [employeeQuiz, setEmployeeQuiz] = useState(null);
  const [quizAnswers, setQuizAnswers] = useState({});
  const [quizResult, setQuizResult] = useState(null);

  const loadHome = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const requests = [api.get("/training/me")];
      if (canManage) requests.push(api.get("/training/courses"));
      if (canAssign) requests.push(api.get("/employees"));

      const responses = await Promise.all(requests);
      const myItems = Array.isArray(responses[0]?.data?.items)
        ? responses[0].data.items
        : [];
      setMyAssignments(myItems);

      let index = 1;
      if (canManage) {
        const managedItems = Array.isArray(responses[index]?.data?.items)
          ? responses[index].data.items
          : [];
        setCourses(managedItems);
        setSelectedCourseId((current) => {
          if (current && managedItems.some((item) => item.id === current)) return current;
          return managedItems[0]?.id || "";
        });
        index += 1;
      }
      if (canAssign) {
        const employeeItems = Array.isArray(responses[index]?.data?.items)
          ? responses[index].data.items
          : [];
        setEmployees(employeeItems);
      }

      setSelectedAssignmentId((current) => {
        if (current && myItems.some((item) => item.id === current)) return current;
        return myItems[0]?.id || "";
      });
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible cargar la capacitación.");
    } finally {
      setLoading(false);
    }
  }, [canAssign, canManage]);

  const loadAdminCourse = useCallback(async (courseId) => {
    if (!canManage || !courseId) {
      setSelectedCourse(null);
      setCourseAssignments([]);
      return;
    }
    setDetailLoading(true);
    try {
      const requests = [api.get(`/training/courses/${courseId}`)];
      if (canViewResults) {
        requests.push(api.get(`/training/courses/${courseId}/assignments`));
      }
      const [courseResponse, assignmentsResponse] = await Promise.all(requests);
      setSelectedCourse(courseResponse.data);
      setCourseAssignments(
        canViewResults && Array.isArray(assignmentsResponse?.data?.items)
          ? assignmentsResponse.data.items
          : [],
      );
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible cargar el curso.");
    } finally {
      setDetailLoading(false);
    }
  }, [canManage, canViewResults]);

  const selectedAssignment = useMemo(
    () => myAssignments.find((assignment) => assignment.id === selectedAssignmentId),
    [myAssignments, selectedAssignmentId],
  );

  const loadEmployeeCourse = useCallback(async (courseId) => {
    if (!courseId) {
      setEmployeeCourse(null);
      setEmployeeQuiz(null);
      return;
    }
    setDetailLoading(true);
    try {
      const { data } = await api.get(`/training/me/courses/${courseId}`);
      setEmployeeCourse(data);
      setQuizResult(null);
      setQuizAnswers({});

      const lessonsComplete = (
        data.course?.lesson_count > 0
        && data.course?.completed_lessons >= data.course?.lesson_count
      );
      if (canTakeQuiz && data.course?.has_quiz && lessonsComplete) {
        const quizResponse = await api.get(`/training/me/courses/${courseId}/quiz`);
        setEmployeeQuiz(quizResponse.data);
      } else {
        setEmployeeQuiz(null);
      }
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible abrir el curso.");
    } finally {
      setDetailLoading(false);
    }
  }, [canTakeQuiz]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadHome();
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadHome]);

  useEffect(() => {
    if (!selectedCourseId) return undefined;
    const timeoutId = window.setTimeout(() => {
      void loadAdminCourse(selectedCourseId);
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadAdminCourse, selectedCourseId]);

  useEffect(() => {
    const courseId = selectedAssignment?.course?.id;
    if (!courseId) return undefined;
    const timeoutId = window.setTimeout(() => {
      void loadEmployeeCourse(courseId);
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadEmployeeCourse, selectedAssignment]);

  async function createCourse(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post("/training/courses", {
        title: courseForm.title.trim(),
        description: courseForm.description.trim() || null,
      });
      setCourseForm({ title: "", description: "" });
      setCreatingCourse(false);
      await loadHome();
      setSelectedCourseId(data.id);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible crear el curso.");
    } finally {
      setSaving(false);
    }
  }

  async function publishCourse() {
    if (!selectedCourseId) return;
    setSaving(true);
    setError("");
    try {
      const { data } = await api.put(`/training/courses/${selectedCourseId}`, {
        status: "PUBLISHED",
      });
      setSelectedCourse(data);
      await loadHome();
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible publicar el curso.");
    } finally {
      setSaving(false);
    }
  }

  async function addModule(event) {
    event.preventDefault();
    if (!selectedCourseId) return;
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post(
        `/training/courses/${selectedCourseId}/modules`,
        {
          title: moduleForm.title.trim(),
          description: moduleForm.description.trim() || null,
        },
      );
      setSelectedCourse(data);
      setModuleForm({ title: "", description: "" });
      await loadHome();
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible agregar el módulo.");
    } finally {
      setSaving(false);
    }
  }

  function lessonForm(moduleId) {
    return lessonForms[moduleId] || {
      title: "",
      description: "",
      video_url: "",
      duration_seconds: "",
    };
  }

  function updateLessonForm(moduleId, patch) {
    setLessonForms((current) => ({
      ...current,
      [moduleId]: {
        ...(current[moduleId] || {
          title: "",
          description: "",
          video_url: "",
          duration_seconds: "",
        }),
        ...patch,
      },
    }));
  }

  async function addLesson(event, moduleId) {
    event.preventDefault();
    const form = lessonForm(moduleId);
    setSaving(true);
    setError("");
    try {
      const duration = form.duration_seconds
        ? Number.parseInt(form.duration_seconds, 10)
        : null;
      const { data } = await api.post(`/training/modules/${moduleId}/lessons`, {
        title: form.title.trim(),
        description: form.description.trim() || null,
        video_url: form.video_url.trim() || null,
        duration_seconds: Number.isInteger(duration) ? duration : null,
      });
      setSelectedCourse(data);
      setLessonForms((current) => ({
        ...current,
        [moduleId]: {
          title: "",
          description: "",
          video_url: "",
          duration_seconds: "",
        },
      }));
      await loadHome();
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible agregar la lección.");
    } finally {
      setSaving(false);
    }
  }

  async function uploadLessonVideo(lessonId, file) {
    if (!file) return;
    const allowedTypes = ["video/mp4", "video/webm", "video/ogg"];
    if (!allowedTypes.includes(file.type)) {
      setError("Formato no soportado. Usa MP4, WebM u OGG.");
      return;
    }
    if (file.size <= 0 || file.size > 1024 * 1024 * 1024) {
      setError("El video debe pesar como máximo 1 GB.");
      return;
    }

    setUploadingLessonId(lessonId);
    setError("");
    try {
      const manifest = {
        filename: file.name,
        content_type: file.type,
        size_bytes: file.size,
      };
      const { data } = await api.post(
        `/training/lessons/${lessonId}/video/upload`,
        manifest,
      );

      const formData = new FormData();
      Object.entries(data.upload.fields || {}).forEach(([key, value]) => {
        formData.append(key, value);
      });
      formData.append("file", file);

      const uploadResponse = await fetch(data.upload.url, {
        method: "POST",
        body: formData,
      });
      if (!uploadResponse.ok) {
        throw new Error("S3 upload failed");
      }

      const finalized = await api.post(
        `/training/lessons/${lessonId}/video/complete`,
        {
          key: data.key,
          content_type: file.type,
          size_bytes: file.size,
        },
      );
      setSelectedCourse(finalized.data);
      await loadHome();
    } catch (err) {
      setError(
        err.response?.data?.detail
          || "No fue posible subir el video. Intenta nuevamente.",
      );
    } finally {
      setUploadingLessonId("");
    }
  }

  async function assignCourse(event) {
    event.preventDefault();
    if (!selectedCourseId || !assignEmployeeId) return;
    setSaving(true);
    setError("");
    try {
      await api.post(
        `/training/courses/${selectedCourseId}/assignments/${assignEmployeeId}`,
      );
      setAssignEmployeeId("");
      await loadAdminCourse(selectedCourseId);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible asignar el curso.");
    } finally {
      setSaving(false);
    }
  }

  async function completeLesson(lessonId) {
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post(
        `/training/me/lessons/${lessonId}/complete`,
      );
      setEmployeeCourse(data);
      await Promise.all([
        loadHome(),
        loadEmployeeCourse(data.course.id),
      ]);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible guardar el avance.");
    } finally {
      setSaving(false);
    }
  }

  async function createQuiz(event) {
    event.preventDefault();
    if (!selectedCourseId) return;
    setSaving(true);
    setError("");
    try {
      await api.post(`/training/courses/${selectedCourseId}/quiz`, {
        title: quizForm.title.trim(),
        passing_score: Number.parseInt(quizForm.passing_score, 10),
      });
      await loadAdminCourse(selectedCourseId);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible crear la evaluación.");
    } finally {
      setSaving(false);
    }
  }

  function updateQuestionOption(index, value) {
    setQuestionForm((current) => ({
      ...current,
      options: current.options.map((option, optionIndex) => (
        optionIndex === index ? value : option
      )),
    }));
  }

  async function addQuizQuestion(event) {
    event.preventDefault();
    const quizId = selectedCourse?.quiz?.id;
    if (!quizId) return;
    setSaving(true);
    setError("");
    try {
      await api.post(`/training/quizzes/${quizId}/questions`, {
        prompt: questionForm.prompt.trim(),
        options: questionForm.options.map((option) => option.trim()),
        correct_option: Number.parseInt(questionForm.correct_option, 10),
      });
      setQuestionForm({
        prompt: "",
        options: ["", "", "", ""],
        correct_option: "0",
      });
      await loadAdminCourse(selectedCourseId);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible agregar la pregunta.");
    } finally {
      setSaving(false);
    }
  }

  async function submitQuiz(event) {
    event.preventDefault();
    const courseId = employeeCourse?.course?.id;
    if (!courseId || !employeeQuiz) return;
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post(
        `/training/me/courses/${courseId}/quiz/attempts`,
        { answers: quizAnswers },
      );
      setQuizResult(data);
      await Promise.all([
        loadHome(),
        loadEmployeeCourse(courseId),
      ]);
      setQuizResult(data);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible enviar la evaluación.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="page-loading"><span /> Preparando capacitación…</div>
      </div>
    );
  }

  return (
    <div className="page training-page">
      <header className="page-header split-header">
        <div>
          <span className="eyebrow">Aprendizaje interno</span>
          <h1>Capacitación</h1>
          <p>Hola, {firstName}. Cursos, videos y progreso en un solo lugar.</p>
        </div>
        {canManage && (
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => setCreatingCourse(true)}
          >
            + Crear curso
          </button>
        )}
      </header>

      {error && <div className="alert" role="alert">{error}</div>}

      {canManage && (
        <section className="training-admin-layout">
          <aside className="panel training-course-sidebar">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Administración</span>
                <h2>Cursos</h2>
              </div>
              <span className="training-count">{courses.length}</span>
            </div>

            {courses.length === 0 ? (
              <div className="empty-state compact">
                <strong>Aún no hay cursos</strong>
                <p>Crea el primer curso de inducción o capacitación.</p>
              </div>
            ) : (
              <div className="training-course-list">
                {courses.map((course) => (
                  <button
                    className={`training-course-row ${course.id === selectedCourseId ? "active" : ""}`}
                    key={course.id}
                    type="button"
                    onClick={() => setSelectedCourseId(course.id)}
                  >
                    <span>
                      <strong>{course.title}</strong>
                      <small>{course.module_count} módulos · {course.lesson_count} lecciones</small>
                    </span>
                    <b className={`training-status training-status-${course.status.toLowerCase()}`}>
                      {course.status === "PUBLISHED" ? "Publicado" : course.status === "ARCHIVED" ? "Archivado" : "Borrador"}
                    </b>
                  </button>
                ))}
              </div>
            )}
          </aside>

          <div className="training-admin-content">
            {detailLoading && !selectedCourse ? (
              <section className="panel page-loading"><span /> Cargando curso…</section>
            ) : selectedCourse ? (
              <>
                <section className="panel training-course-overview">
                  <div>
                    <span className="eyebrow">Editor de curso</span>
                    <h2>{selectedCourse.title}</h2>
                    <p>{selectedCourse.description || "Sin descripción."}</p>
                  </div>
                  <div className="training-course-overview-actions">
                    <span className={`training-status training-status-${selectedCourse.status.toLowerCase()}`}>
                      {selectedCourse.status === "PUBLISHED" ? "Publicado" : selectedCourse.status === "ARCHIVED" ? "Archivado" : "Borrador"}
                    </span>
                    {selectedCourse.status === "DRAFT" && (
                      <button
                        className="btn btn-primary"
                        type="button"
                        onClick={publishCourse}
                        disabled={saving}
                      >
                        Publicar curso
                      </button>
                    )}
                  </div>
                </section>

                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <span className="eyebrow">Contenido</span>
                      <h2>Módulos y lecciones</h2>
                    </div>
                  </div>

                  <div className="training-module-list">
                    {selectedCourse.modules?.map((module) => (
                      <article className="training-module-card" key={module.id}>
                        <div className="training-module-header">
                          <div>
                            <span>Módulo {module.position}</span>
                            <h3>{module.title}</h3>
                            {module.description && <p>{module.description}</p>}
                          </div>
                          <strong>{module.lessons?.length || 0} lecciones</strong>
                        </div>

                        <div className="training-lesson-list">
                          {module.lessons?.map((lesson) => (
                            <div className="training-lesson-row training-lesson-admin-row" key={lesson.id}>
                              <span className="training-play" aria-hidden="true">▶</span>
                              <div className="training-lesson-admin-copy">
                                <strong>{lesson.title}</strong>
                                <small>
                                  {lesson.video_url
                                    ? lesson.video_source === "managed"
                                      ? "Video privado en S3"
                                      : "Video por URL externa"
                                    : "Sin video"}
                                  {lesson.duration_seconds ? ` · ${Math.ceil(lesson.duration_seconds / 60)} min` : ""}
                                </small>
                                {lesson.video_size_bytes ? (
                                  <small>{Math.max(1, Math.round(lesson.video_size_bytes / (1024 * 1024)))} MB</small>
                                ) : null}
                              </div>
                              {selectedCourse.status === "DRAFT" && (
                                <label className={`training-video-upload-button ${uploadingLessonId === lesson.id ? "is-uploading" : ""}`}>
                                  <span>
                                    {uploadingLessonId === lesson.id
                                      ? "Subiendo…"
                                      : lesson.video_url
                                        ? "Reemplazar video"
                                        : "Subir video"}
                                  </span>
                                  <input
                                    type="file"
                                    accept="video/mp4,video/webm,video/ogg"
                                    disabled={Boolean(uploadingLessonId)}
                                    onChange={(event) => {
                                      const file = event.target.files?.[0];
                                      event.target.value = "";
                                      void uploadLessonVideo(lesson.id, file);
                                    }}
                                  />
                                </label>
                              )}
                            </div>
                          ))}
                        </div>

                        {selectedCourse.status === "DRAFT" && (
                          <form className="training-inline-form" onSubmit={(event) => addLesson(event, module.id)}>
                            <strong>Nueva lección</strong>
                            <input
                              aria-label={`Título de lección para ${module.title}`}
                              placeholder="Título de la lección"
                              value={lessonForm(module.id).title}
                              onChange={(event) => updateLessonForm(module.id, { title: event.target.value })}
                              required
                            />
                            <textarea
                              aria-label={`Descripción de lección para ${module.title}`}
                              placeholder="Descripción breve"
                              value={lessonForm(module.id).description}
                              onChange={(event) => updateLessonForm(module.id, { description: event.target.value })}
                              rows="2"
                            />
                            <div className="training-inline-grid">
                              <input
                                aria-label={`URL de video para ${module.title}`}
                                type="url"
                                placeholder="https://.../video.mp4"
                                value={lessonForm(module.id).video_url}
                                onChange={(event) => updateLessonForm(module.id, { video_url: event.target.value })}
                              />
                              <input
                                aria-label={`Duración de lección para ${module.title}`}
                                type="number"
                                min="1"
                                placeholder="Duración (segundos)"
                                value={lessonForm(module.id).duration_seconds}
                                onChange={(event) => updateLessonForm(module.id, { duration_seconds: event.target.value })}
                              />
                            </div>
                            <button className="btn btn-secondary" type="submit" disabled={saving}>
                              Agregar lección
                            </button>
                          </form>
                        )}
                      </article>
                    ))}
                  </div>

                  {selectedCourse.status === "DRAFT" && (
                    <form className="training-module-form" onSubmit={addModule}>
                      <span className="eyebrow">Nuevo módulo</span>
                      <div className="training-inline-grid">
                        <input
                          aria-label="Título del módulo"
                          placeholder="Ej. Bienvenida a ASIATI"
                          value={moduleForm.title}
                          onChange={(event) => setModuleForm({ ...moduleForm, title: event.target.value })}
                          required
                        />
                        <input
                          aria-label="Descripción del módulo"
                          placeholder="Descripción breve"
                          value={moduleForm.description}
                          onChange={(event) => setModuleForm({ ...moduleForm, description: event.target.value })}
                        />
                      </div>
                      <button className="btn btn-secondary" type="submit" disabled={saving}>
                        + Agregar módulo
                      </button>
                    </form>
                  )}
                </section>

                <section className="panel training-quiz-admin">
                  <div className="panel-heading">
                    <div>
                      <span className="eyebrow">Evaluación</span>
                      <h2>Quiz del curso</h2>
                    </div>
                    {selectedCourse.quiz && (
                      <span className="training-status training-status-published">
                        Aprueba con {selectedCourse.quiz.passing_score}%
                      </span>
                    )}
                  </div>

                  {!selectedCourse.quiz ? (
                    selectedCourse.status === "DRAFT" ? (
                      <form className="training-quiz-create-form" onSubmit={createQuiz}>
                        <div className="training-inline-grid">
                          <input
                            aria-label="Título de la evaluación"
                            value={quizForm.title}
                            onChange={(event) => setQuizForm({ ...quizForm, title: event.target.value })}
                            placeholder="Evaluación final"
                            required
                          />
                          <input
                            aria-label="Puntaje mínimo para aprobar"
                            type="number"
                            min="1"
                            max="100"
                            value={quizForm.passing_score}
                            onChange={(event) => setQuizForm({ ...quizForm, passing_score: event.target.value })}
                            required
                          />
                        </div>
                        <button className="btn btn-secondary" type="submit" disabled={saving}>
                          + Crear evaluación
                        </button>
                      </form>
                    ) : (
                      <div className="empty-state compact">
                        <strong>Curso sin evaluación</strong>
                        <p>Este curso se completa únicamente con sus lecciones.</p>
                      </div>
                    )
                  ) : (
                    <div className="training-quiz-admin-body">
                      <div className="training-quiz-summary">
                        <div>
                          <strong>{selectedCourse.quiz.title}</strong>
                          <small>{selectedCourse.quiz.question_count} preguntas · mínimo {selectedCourse.quiz.passing_score}%</small>
                        </div>
                      </div>

                      {selectedCourse.quiz.questions?.length > 0 && (
                        <div className="training-quiz-question-list">
                          {selectedCourse.quiz.questions.map((question) => (
                            <article className="training-quiz-question-admin" key={question.id}>
                              <span>{question.position}</span>
                              <div>
                                <strong>{question.prompt}</strong>
                                <ol type="A">
                                  {question.options.map((option, index) => (
                                    <li className={index === question.correct_option ? "is-correct" : ""} key={option}>
                                      {option}
                                    </li>
                                  ))}
                                </ol>
                              </div>
                            </article>
                          ))}
                        </div>
                      )}

                      {selectedCourse.status === "DRAFT" && (
                        <form className="training-quiz-question-form" onSubmit={addQuizQuestion}>
                          <strong>Nueva pregunta</strong>
                          <textarea
                            aria-label="Pregunta de evaluación"
                            rows="2"
                            value={questionForm.prompt}
                            onChange={(event) => setQuestionForm({ ...questionForm, prompt: event.target.value })}
                            placeholder="Escribe la pregunta"
                            required
                          />
                          <div className="training-quiz-options-grid">
                            {questionForm.options.map((option, index) => (
                              <input
                                key={index}
                                aria-label={`Opción ${index + 1}`}
                                value={option}
                                onChange={(event) => updateQuestionOption(index, event.target.value)}
                                placeholder={`Opción ${index + 1}`}
                                required
                              />
                            ))}
                          </div>
                          <div className="training-quiz-question-actions">
                            <select
                              aria-label="Respuesta correcta"
                              value={questionForm.correct_option}
                              onChange={(event) => setQuestionForm({ ...questionForm, correct_option: event.target.value })}
                            >
                              {questionForm.options.map((_, index) => (
                                <option key={index} value={String(index)}>Correcta: opción {index + 1}</option>
                              ))}
                            </select>
                            <button className="btn btn-secondary" type="submit" disabled={saving}>
                              Agregar pregunta
                            </button>
                          </div>
                        </form>
                      )}
                    </div>
                  )}
                </section>

                {canAssign && (
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <span className="eyebrow">Distribución</span>
                        <h2>Asignar a un empleado</h2>
                      </div>
                    </div>
                    <form className="training-assignment-form" onSubmit={assignCourse}>
                      <select
                        aria-label="Empleado para asignar"
                        value={assignEmployeeId}
                        onChange={(event) => setAssignEmployeeId(event.target.value)}
                        required
                      >
                        <option value="">Selecciona un empleado</option>
                        {employees.map((employee) => (
                          <option key={employee.id} value={employee.id}>
                            {[employee.first_name, employee.last_name].filter(Boolean).join(" ") || employee.email}
                          </option>
                        ))}
                      </select>
                      <button
                        className="btn btn-primary"
                        type="submit"
                        disabled={saving || selectedCourse.status !== "PUBLISHED"}
                      >
                        Asignar curso
                      </button>
                    </form>
                    {selectedCourse.status !== "PUBLISHED" && (
                      <p className="training-form-note">Publica el curso antes de asignarlo.</p>
                    )}

                    {canViewResults && courseAssignments.length > 0 && (
                      <div className="training-results-list">
                        {courseAssignments.map((assignment) => (
                          <div className="training-result-row" key={assignment.id}>
                            <div>
                              <strong>
                                {[assignment.employee.first_name, assignment.employee.last_name].filter(Boolean).join(" ")
                                  || assignment.employee.email}
                              </strong>
                              <small>{assignment.employee.job_title || assignment.employee.department || assignment.employee.email}</small>
                              {assignment.quiz_result && (
                                <small>
                                  Quiz: {assignment.quiz_result.latest_score ?? "—"}%
                                  {assignment.quiz_result.passed ? " · aprobado" : assignment.quiz_result.attempt_count ? " · pendiente" : " · sin intento"}
                                </small>
                              )}
                            </div>
                            <div className="training-result-progress">
                              <span>{assignment.course.progress_percent}%</span>
                              <div><i style={{ width: `${assignment.course.progress_percent}%` }} /></div>
                            </div>
                            <span className="training-status training-status-published">
                              {assignment.status === "COMPLETED" ? "Completado" : "En curso"}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                )}
              </>
            ) : (
              <section className="panel empty-state">
                <strong>Selecciona o crea un curso</strong>
                <p>Desde aquí podrás construir sus módulos, videos y asignaciones.</p>
              </section>
            )}
          </div>
        </section>
      )}

      <section className={`training-learning-section ${canManage ? "training-learning-after-admin" : ""}`}>
        <div className="training-section-heading">
          <div>
            <span className="eyebrow">Mi aprendizaje</span>
            <h2>Mis cursos</h2>
          </div>
          <span>{myAssignments.length} asignados</span>
        </div>

        {myAssignments.length === 0 ? (
          <section className="panel empty-state training-empty">
            <span className="training-mark" aria-hidden="true">▶</span>
            <strong>Aún no tienes cursos asignados</strong>
            <p>Cuando se publique una capacitación para tu perfil aparecerá aquí.</p>
          </section>
        ) : (
          <div className="training-learning-layout">
            <aside className="training-assignment-list">
              {myAssignments.map((assignment) => (
                <button
                  key={assignment.id}
                  type="button"
                  className={`training-assignment-card ${assignment.id === selectedAssignmentId ? "active" : ""}`}
                  onClick={() => setSelectedAssignmentId(assignment.id)}
                >
                  <div>
                    <span className="training-status training-status-published">
                      {assignment.status === "COMPLETED" ? "Completado" : "En curso"}
                    </span>
                    <h3>{assignment.course.title}</h3>
                    <p>{assignment.course.description || "Capacitación ASIATI"}</p>
                  </div>
                  <div className="training-progress">
                    <span><strong>{courseProgress(assignment.course)}%</strong> completado</span>
                    <div><i style={{ width: `${courseProgress(assignment.course)}%` }} /></div>
                  </div>
                </button>
              ))}
            </aside>

            <section className="panel training-player-panel">
              {detailLoading && !employeeCourse ? (
                <div className="page-loading"><span /> Cargando contenido…</div>
              ) : employeeCourse?.course ? (
                <>
                  <div className="training-player-heading">
                    <div>
                      <span className="eyebrow">Curso asignado</span>
                      <h2>{employeeCourse.course.title}</h2>
                      <p>{employeeCourse.course.description || "Capacitación ASIATI"}</p>
                    </div>
                    <strong>{employeeCourse.course.progress_percent}%</strong>
                  </div>

                  <div className="training-module-list">
                    {employeeCourse.course.modules?.map((module) => (
                      <article className="training-module-card training-module-consume" key={module.id}>
                        <div className="training-module-header">
                          <div>
                            <span>Módulo {module.position}</span>
                            <h3>{module.title}</h3>
                          </div>
                        </div>

                        <div className="training-lesson-consume-list">
                          {module.lessons?.map((lesson) => (
                            <article className={`training-consume-lesson ${lesson.completed ? "is-complete" : ""}`} key={lesson.id}>
                              <div className="training-consume-heading">
                                <div>
                                  <span className="training-play" aria-hidden="true">{lesson.completed ? "✓" : "▶"}</span>
                                  <div>
                                    <strong>{lesson.title}</strong>
                                    {lesson.description && <p>{lesson.description}</p>}
                                  </div>
                                </div>
                                {lesson.completed ? (
                                  <span className="status-pill"><i /> Completada</span>
                                ) : (
                                  <button
                                    className="btn btn-secondary"
                                    type="button"
                                    onClick={() => completeLesson(lesson.id)}
                                    disabled={saving}
                                  >
                                    Marcar completada
                                  </button>
                                )}
                              </div>

                              {lesson.video_url && (
                                <div className="training-video">
                                  {isDirectVideo(lesson.video_url) ? (
                                    <video controls preload="metadata">
                                      <source src={lesson.video_url} />
                                      Tu navegador no puede reproducir este video.
                                    </video>
                                  ) : (
                                    <a
                                      className="btn btn-ghost"
                                      href={lesson.video_url}
                                      target="_blank"
                                      rel="noreferrer"
                                    >
                                      Abrir video ↗
                                    </a>
                                  )}
                                </div>
                              )}
                            </article>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>

                  {employeeCourse.course.has_quiz && (
                    <section className="training-quiz-employee">
                      <div className="training-quiz-employee-heading">
                        <div>
                          <span className="eyebrow">Evaluación final</span>
                          <h3>{employeeQuiz?.title || "Quiz del curso"}</h3>
                        </div>
                        {employeeQuiz && (
                          <span className="training-status training-status-published">
                            Mínimo {employeeQuiz.passing_score}%
                          </span>
                        )}
                      </div>

                      {employeeCourse.course.completed_lessons < employeeCourse.course.lesson_count ? (
                        <div className="training-quiz-lock">
                          <strong>Completa todas las lecciones para habilitar la evaluación.</strong>
                        </div>
                      ) : employeeQuiz ? (
                        <form className="training-quiz-attempt-form" onSubmit={submitQuiz}>
                          {employeeQuiz.attempts?.length > 0 && (
                            <div className="training-quiz-attempt-history">
                              <span>Intentos anteriores</span>
                              {employeeQuiz.attempts.map((attempt) => (
                                <b className={attempt.passed ? "score-positive" : "score-negative"} key={attempt.id}>
                                  #{attempt.attempt_number}: {attempt.score_percent}% {attempt.passed ? "✓" : ""}
                                </b>
                              ))}
                            </div>
                          )}

                          {employeeQuiz.questions.map((question, questionIndex) => (
                            <fieldset className="training-quiz-question" key={question.id}>
                              <legend>{questionIndex + 1}. {question.prompt}</legend>
                              {question.options.map((option, optionIndex) => (
                                <label key={option}>
                                  <input
                                    type="radio"
                                    name={`quiz-${question.id}`}
                                    value={optionIndex}
                                    checked={quizAnswers[question.id] === optionIndex}
                                    onChange={() => setQuizAnswers((current) => ({
                                      ...current,
                                      [question.id]: optionIndex,
                                    }))}
                                    required
                                  />
                                  <span>{option}</span>
                                </label>
                              ))}
                            </fieldset>
                          ))}

                          {quizResult && (
                            <div className={`training-quiz-result ${quizResult.attempt.passed ? "is-pass" : "is-fail"}`}>
                              <strong>{quizResult.attempt.score_percent}%</strong>
                              <span>
                                {quizResult.attempt.passed
                                  ? "Evaluación aprobada. Curso completado."
                                  : `Aún no alcanzas el ${quizResult.passing_score}%. Puedes intentarlo de nuevo.`}
                              </span>
                            </div>
                          )}

                          <button
                            className="btn btn-primary"
                            type="submit"
                            disabled={saving || Object.keys(quizAnswers).length !== employeeQuiz.question_count}
                          >
                            {saving ? "Enviando…" : "Enviar evaluación"}
                          </button>
                        </form>
                      ) : (
                        <div className="page-loading compact-loading"><span /> Preparando evaluación…</div>
                      )}
                    </section>
                  )}
                </>
              ) : (
                <div className="empty-state">
                  <strong>Selecciona un curso</strong>
                  <p>Abre una capacitación para ver sus módulos y lecciones.</p>
                </div>
              )}
            </section>
          </div>
        )}
      </section>

      {creatingCourse && (
        <div className="modal-overlay" role="presentation" onMouseDown={() => setCreatingCourse(false)}>
          <section className="modal training-course-modal" role="dialog" aria-modal="true" aria-labelledby="create-course-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <span className="eyebrow">Nuevo contenido</span>
                <h2 id="create-course-title">Crear curso</h2>
                <p>Comienza con la información general. Después podrás agregar módulos y videos.</p>
              </div>
              <button className="btn-close" type="button" aria-label="Cerrar" onClick={() => setCreatingCourse(false)}>×</button>
            </div>
            <form onSubmit={createCourse}>
              <div className="form-group">
                <label htmlFor="training-course-title">Título</label>
                <input
                  id="training-course-title"
                  value={courseForm.title}
                  onChange={(event) => setCourseForm({ ...courseForm, title: event.target.value })}
                  placeholder="Ej. Inducción ASIATI"
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="training-course-description">Descripción</label>
                <textarea
                  id="training-course-description"
                  rows="4"
                  value={courseForm.description}
                  onChange={(event) => setCourseForm({ ...courseForm, description: event.target.value })}
                  placeholder="Objetivo y contexto del curso"
                />
              </div>
              <div className="form-actions">
                <button className="btn btn-secondary" type="button" onClick={() => setCreatingCourse(false)}>Cancelar</button>
                <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? "Creando…" : "Crear curso"}</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

export default Training;
