"""Interface-only translations. Theme names, papers, answers and subject data stay original."""
LANGUAGES = (
    ('en_US', 'English (American)'), ('en_GB', 'English (British)'),
    ('es', 'Español — Spanish'), ('hi', 'हिन्दी — Hindi'), ('fr', 'Français — French'),
)

# source | Spanish | Hindi | French. Keep stable English keys out of application state.
_ROWS = '''
Profile|Perfil|प्रोफ़ाइल|Profil
Name (optional)|Nombre (opcional)|नाम (वैकल्पिक)|Nom (facultatif)
Your name|Tu nombre|आपका नाम|Votre nom
Profile picture|Foto de perfil|प्रोफ़ाइल चित्र|Photo de profil
Change|Cambiar|बदलें|Modifier
Remove|Eliminar|हटाएँ|Supprimer
Student|Estudiante|विद्यार्थी|Élève
Open Settings|Abrir ajustes|सेटिंग्स खोलें|Ouvrir les paramètres
App behavior|Comportamiento de la aplicación|ऐप का व्यवहार|Comportement de l’application
Choose profile picture|Elegir foto de perfil|प्रोफ़ाइल चित्र चुनें|Choisir une photo de profil
This image could not be opened. Choose another image.|No se pudo abrir esta imagen. Elige otra.|यह चित्र नहीं खोला जा सका। दूसरा चित्र चुनें।|Impossible d’ouvrir cette image. Choisissez-en une autre.
Dashboard|Inicio|डैशबोर्ड|Accueil
May/June|Mayo/Junio|मई/जून|Mai/Juin
October/November|Octubre/Noviembre|अक्टूबर/नवंबर|Octobre/Novembre
February/March|Febrero/Marzo|फ़रवरी/मार्च|Février/Mars
View results|Ver resultados|परिणाम देखें|Voir les résultats
Good morning|Buenos días|सुप्रभात|Bonjour
Good afternoon|Buenas tardes|नमस्कार|Bon après-midi
Good evening|Buenas noches|शुभ संध्या|Bonsoir
{greeting}, {name}|{greeting}, {name}|{greeting}, {name}|{greeting}, {name}
Pick up where you left off.|Continúa donde lo dejaste.|जहाँ छोड़ा था वहीं से जारी रखें।|Reprenez là où vous en étiez.
No activity yet|Aún no hay actividad|अभी कोई गतिविधि नहीं|Aucune activité pour le moment
Search for a paper to begin.|Busca un examen para empezar.|शुरू करने के लिए प्रश्नपत्र खोजें।|Recherchez un sujet pour commencer.
Open Documentation|Abrir documentación|दस्तावेज़ खोलें|Ouvrir la documentation
Back to results|Volver a los resultados|परिणामों पर लौटें|Retour aux résultats
Back to Dashboard|Volver al inicio|डैशबोर्ड पर लौटें|Retour à l’accueil
Practiced|Practicados|अभ्यास किया|Entraînements
Attempted|Intentados|परीक्षा प्रयास|Examens tentés
{count} papers|{count} exámenes|{count} प्रश्नपत्र|{count} sujets
{count} sessions|{count} sesiones|{count} सत्र|{count} séances
{count} exams|{count} exámenes|{count} परीक्षाएँ|{count} examens
Recent Activity|Actividad reciente|हाल की गतिविधि|Activité récente
Continue where you left off|Continúa donde lo dejaste|जहाँ छोड़ा था वहीं से जारी रखें|Reprendre votre travail
Flagged Papers|Exámenes marcados|चिह्नित प्रश्नपत्र|Sujets signalés
{count} flagged questions|{count} preguntas marcadas|{count} चिह्नित प्रश्न|{count} questions signalées
View all activity|Ver toda la actividad|सभी गतिविधियाँ देखें|Voir toute l’activité
View all flagged papers|Ver todos los exámenes marcados|सभी चिह्नित प्रश्नपत्र देखें|Voir tous les sujets signalés
Flag questions during a session to find them here.|Marca preguntas durante una sesión para encontrarlas aquí.|सत्र में प्रश्न चिह्नित करें ताकि वे यहाँ दिखें।|Signalez des questions pendant une séance pour les retrouver ici.
No flagged papers yet.|Aún no hay exámenes marcados.|अभी कोई चिह्नित प्रश्नपत्र नहीं।|Aucun sujet signalé pour le moment.
No activity in this mode yet.|Aún no hay actividad en este modo.|इस मोड में अभी कोई गतिविधि नहीं।|Aucune activité dans ce mode pour le moment.
Paper history|Historial del examen|प्रश्नपत्र इतिहास|Historique du sujet
Attempt details|Detalles del intento|प्रयास विवरण|Détails de la tentative
Open attempt|Abrir intento|प्रयास खोलें|Ouvrir la tentative
View saved answers|Ver respuestas guardadas|सहेजे गए उत्तर देखें|Voir les réponses enregistrées
View paper history|Ver historial del examen|प्रश्नपत्र इतिहास देखें|Voir l’historique du sujet
Open paper|Abrir examen|प्रश्नपत्र खोलें|Ouvrir le sujet
Practice again|Practicar de nuevo|फिर अभ्यास करें|S’entraîner à nouveau
Take exam again|Repetir examen|फिर परीक्षा दें|Repasser l’examen
Resume at flagged question|Continuar en la pregunta marcada|चिह्नित प्रश्न से जारी रखें|Reprendre à la question signalée
Flagged questions: {questions}|Preguntas marcadas: {questions}|चिह्नित प्रश्न: {questions}|Questions signalées : {questions}
{answered} / {total} answered|{answered} / {total} respondidas|{answered} / {total} उत्तर दिए|{answered} / {total} répondues
{answered} / {total} answered · {time} elapsed|{answered} / {total} respondidas · {time} transcurrido|{answered} / {total} उत्तर दिए · {time} बीता|{answered} / {total} répondues · {time} écoulé
Started|Iniciado|शुरू किया|Commencé
Saved|Guardado|सहेजा गया|Enregistré
Completed|Completado|पूरा हुआ|Terminé
Abandoned|Abandonado|छोड़ा गया|Abandonné
Date unavailable|Fecha no disponible|तिथि उपलब्ध नहीं|Date indisponible
Series unavailable|Serie no disponible|श्रृंखला उपलब्ध नहीं|Session indisponible
Time spent: {time}|Tiempo dedicado: {time}|लगा समय: {time}|Temps passé : {time}
Score: {score}/{total}|Puntuación: {score}/{total}|अंक: {score}/{total}|Note : {score}/{total}
Provisional|Provisional|अनंतिम|Provisoire
Saved grading result|Resultado de evaluación guardado|सहेजा गया मूल्यांकन|Résultat enregistré
No saved answers are available.|No hay respuestas guardadas.|कोई सहेजा गया उत्तर उपलब्ध नहीं।|Aucune réponse enregistrée disponible.
Open drawing|Abrir dibujo|चित्र खोलें|Ouvrir le dessin
This attempt has no readable answer snapshot. You can still open the paper or start again.|Este intento no tiene respuestas legibles guardadas. Puedes abrir el examen o empezar de nuevo.|इस प्रयास के सहेजे गए उत्तर उपलब्ध नहीं हैं। प्रश्नपत्र खोल सकते हैं या फिर शुरू कर सकते हैं।|Les réponses enregistrées de cette tentative sont indisponibles. Vous pouvez ouvrir le sujet ou recommencer.
Study history could not be loaded. Your saved attempts are unchanged.|No se pudo cargar el historial. Tus intentos guardados no han cambiado.|अध्ययन इतिहास लोड नहीं हुआ। आपके सहेजे गए प्रयास सुरक्षित हैं।|Impossible de charger l’historique. Vos tentatives enregistrées restent intactes.
Retry|Reintentar|फिर प्रयास करें|Réessayer
Settings|Ajustes|सेटिंग्स|Paramètres
General|General|सामान्य|Général
Appearance|Apariencia|रूप-रंग|Apparence
General Preferences|Preferencias generales|सामान्य प्राथमिकताएँ|Préférences générales
Language|Idioma|भाषा|Langue
Interface language only; papers and your answers stay unchanged.|Solo el idioma de la interfaz; los exámenes y tus respuestas no cambian.|केवल इंटरफ़ेस की भाषा; प्रश्नपत्र और आपके उत्तर नहीं बदलेंगे।|Langue de l’interface uniquement ; les sujets et vos réponses restent inchangés.
Control behavior, look and AI configuration.|Configura el funcionamiento, la apariencia y la IA.|व्यवहार, रूप-रंग और AI कॉन्फ़िगरेशन नियंत्रित करें।|Réglez le fonctionnement, l’apparence et la configuration IA.
Sound|Sonido|ध्वनि|Son
System Accent|Color del sistema|सिस्टम रंग|Couleur du système
Scale Overlay|Escala superpuesta|मापनी ओवरले|Échelle superposée
Show Startup Animation|Mostrar animación de inicio|शुरुआती एनीमेशन दिखाएँ|Afficher l’animation au démarrage
Full Screen on Startup|Pantalla completa al iniciar|शुरुआत में पूर्ण स्क्रीन|Plein écran au démarrage
Actions|Acciones|कार्रवाइयाँ|Actions
User Documentation|Documentación de usuario|उपयोगकर्ता दस्तावेज़|Documentation utilisateur
Open Docs|Abrir documentación|दस्तावेज़ खोलें|Ouvrir la documentation
Open quick usage docs and shortcuts.|Abre la guía de uso y los atajos.|उपयोग गाइड और शॉर्टकट खोलें।|Ouvrez le guide d’utilisation et les raccourcis.
AI Configuration|Configuración de IA|AI कॉन्फ़िगरेशन|Configuration IA
AI Config|Configuración IA|AI सेटिंग्स|Configuration IA
Open AI Config|Abrir configuración IA|AI सेटिंग्स खोलें|Ouvrir la configuration IA
Go to AI Config section.|Ir a la sección de configuración de IA.|AI सेटिंग्स अनुभाग पर जाएँ।|Accéder à la configuration IA.
Global Font|Fuente global|ऐप का फ़ॉन्ट|Police générale
Random Theme on Startup|Tema aleatorio al iniciar|शुरुआत में यादृच्छिक थीम|Thème aléatoire au démarrage
Custom Theme Creator · Beta|Creador de temas · Beta|कस्टम थीम निर्माता · बीटा|Créateur de thèmes · Bêta
Custom Theme Creator|Creador de temas|कस्टम थीम निर्माता|Créateur de thèmes
Theme Cards|Temas|थीम कार्ड|Thèmes
Pick a theme from the gallery. Cards show primary and secondary palette colors.|Elige un tema. Las tarjetas muestran los colores principales y secundarios.|गैलरी से थीम चुनें। कार्ड मुख्य और द्वितीयक रंग दिखाते हैं।|Choisissez un thème. Les cartes affichent les couleurs principales et secondaires.
Search themes...|Buscar temas...|थीम खोजें...|Rechercher des thèmes...
Classic|Clásicos|क्लासिक|Classiques
Solid Colors|Colores sólidos|एकरंगी थीम|Couleurs unies
Signature Themes|Temas exclusivos|विशिष्ट थीम|Thèmes signature
Custom|Personalizados|कस्टम|Personnalisés
Save|Guardar|सहेजें|Enregistrer
Save Changes|Guardar cambios|बदलाव सहेजें|Enregistrer les modifications
Save AI Settings|Guardar ajustes de IA|AI सेटिंग्स सहेजें|Enregistrer les paramètres IA
Refresh|Actualizar|रिफ़्रेश|Actualiser
Groq API Key|Clave API de Groq|Groq API कुंजी|Clé API Groq
Text Model|Modelo de texto|टेक्स्ट मॉडल|Modèle de texte
Vision Model|Modelo de visión|विज़न मॉडल|Modèle de vision
Control Center|Centro de control|नियंत्रण केंद्र|Centre de contrôle
Search|Buscar|खोज|Recherche
History|Historial|इतिहास|Historique
Subjects|Asignaturas|विषय|Matières
Subject|Asignatura|विषय|Matière
Search subjects or codes…|Buscar asignaturas o códigos…|विषय या कोड खोजें…|Rechercher des matières ou des codes…
Type subject name or code...|Escribe la asignatura o el código...|विषय का नाम या कोड लिखें...|Saisissez une matière ou un code...
Select a subject to begin|Selecciona una asignatura para empezar|शुरू करने के लिए विषय चुनें|Choisissez une matière pour commencer
Sciences|Ciencias|विज्ञान|Sciences
Mathematics|Matemáticas|गणित|Mathématiques
Languages|Idiomas|भाषाएँ|Langues
Other|Otros|अन्य|Autres
Series|Convocatorias|परीक्षा सत्र|Sessions
Years|Años|वर्ष|Années
Paper Components|Componentes del examen|प्रश्नपत्र घटक|Composantes du sujet
Components|Componentes|घटक|Composantes
Document Options|Opciones de documentos|दस्तावेज़ विकल्प|Options des documents
Document Types|Tipos de documentos|दस्तावेज़ प्रकार|Types de documents
Search Papers|Buscar exámenes|प्रश्नपत्र खोजें|Rechercher des sujets
Cancel Search|Cancelar búsqueda|खोज रद्द करें|Annuler la recherche
Search Results|Resultados de búsqueda|खोज परिणाम|Résultats de recherche
No Results|Sin resultados|कोई परिणाम नहीं|Aucun résultat
No Papers Found|No se encontraron exámenes|कोई प्रश्नपत्र नहीं मिला|Aucun sujet trouvé
No matching papers yet|Aún no hay exámenes coincidentes|अभी कोई मेल खाता प्रश्नपत्र नहीं|Aucun sujet correspondant pour le moment
Search for papers to get started|Busca exámenes para empezar|शुरू करने के लिए प्रश्नपत्र खोजें|Recherchez des sujets pour commencer
List|Lista|सूची|Liste
Grid|Cuadrícula|ग्रिड|Grille
Open All|Abrir todos|सभी खोलें|Tout ouvrir
Download All|Descargar todos|सभी डाउनलोड करें|Tout télécharger
Open|Abrir|खोलें|Ouvrir
Download|Descargar|डाउनलोड करें|Télécharger
Quick Look|Vista rápida|त्वरित दृश्य|Aperçu rapide
Start Exam|Iniciar examen|परीक्षा शुरू करें|Commencer l’examen
Launch Exam Mode|Iniciar modo examen|परीक्षा मोड शुरू करें|Lancer le mode examen
Exam Level:|Nivel:|परीक्षा स्तर:|Niveau :
Recent Searches|Búsquedas recientes|हाल की खोजें|Recherches récentes
Saved Attempts|Intentos guardados|सहेजे गए प्रयास|Tentatives enregistrées
Continue|Continuar|जारी रखें|Continuer
Resume|Reanudar|फिर शुरू करें|Reprendre
Delete|Eliminar|हटाएँ|Supprimer
Clear History|Borrar historial|इतिहास साफ़ करें|Effacer l’historique
Clear|Borrar|साफ़ करें|Effacer
Ready|Listo|तैयार|Prêt
Searching...|Buscando...|खोज जारी है...|Recherche en cours...
Search cancelled|Búsqueda cancelada|खोज रद्द हुई|Recherche annulée
How would you like to work?|¿Cómo quieres trabajar?|आप कैसे अभ्यास करना चाहते हैं?|Comment souhaitez-vous travailler ?
Practice at your own pace, or simulate a timed exam.|Practica a tu ritmo o simula un examen cronometrado.|अपनी गति से अभ्यास करें या समयबद्ध परीक्षा दें।|Entraînez-vous à votre rythme ou simulez un examen chronométré.
Practice Mode|Modo práctica|अभ्यास मोड|Mode entraînement
Exam Mode|Modo examen|परीक्षा मोड|Mode examen
Practice|Práctica|अभ्यास|Entraînement
Exam|Examen|परीक्षा|Examen
Questions|Preguntas|प्रश्न|Questions
Question Navigator|Navegador de preguntas|प्रश्न नेविगेटर|Navigation des questions
Answer Workspace|Espacio de respuestas|उत्तर कार्यक्षेत्र|Espace de réponse
Answer|Respuesta|उत्तर|Réponse
Answers|Respuestas|उत्तर|Réponses
Page not mapped|Página sin asignar|पृष्ठ निर्धारित नहीं|Page non associée
Previous Question|Pregunta anterior|पिछला प्रश्न|Question précédente
Next Question|Pregunta siguiente|अगला प्रश्न|Question suivante
Answers save automatically|Las respuestas se guardan automáticamente|उत्तर अपने आप सहेजे जाते हैं|Les réponses sont enregistrées automatiquement
Pause|Pausar|रोकें|Pause
Paused|En pausa|रुका हुआ|En pause
Navigator|Navegador|नेविगेटर|Navigation
Tools|Herramientas|उपकरण|Outils
Focus|Concentración|फ़ोकस|Concentration
Focus Mode|Modo concentración|फ़ोकस मोड|Mode concentration
Exit Focus|Salir de concentración|फ़ोकस से बाहर|Quitter la concentration
Finish Practice|Terminar práctica|अभ्यास समाप्त करें|Terminer l’entraînement
Finish Exam|Terminar examen|परीक्षा समाप्त करें|Terminer l’examen
End Exam|Finalizar examen|परीक्षा समाप्त करें|Terminer l’examen
Submit|Entregar|जमा करें|Soumettre
Grading|Calificación|मूल्यांकन|Correction
Manual Grading|Calificación manual|मैन्युअल मूल्यांकन|Correction manuelle
AI Grading|Calificación con IA|AI मूल्यांकन|Correction IA
Download MS|Descargar soluciones|अंक योजना डाउनलोड करें|Télécharger le corrigé
View mark scheme|Ver soluciones|अंक योजना देखें|Voir le corrigé
Mark Scheme|Esquema de calificación|अंक योजना|Corrigé
← Back to Question Paper|← Volver al examen|← प्रश्नपत्र पर वापस|← Revenir au sujet
Question Paper|Cuestionario|प्रश्नपत्र|Sujet
⚑ Flag|⚑ Marcar|⚑ चिह्नित करें|⚑ Signaler
⚑ Flagged|⚑ Marcada|⚑ चिह्नित|⚑ Signalée
Answered|Respondida|उत्तर दिया|Répondue
Unanswered|Sin responder|अनुत्तरित|Sans réponse
Flagged|Marcada|चिह्नित|Signalée
Fit|Ajustar|फ़िट|Ajuster
Fit to Page|Ajustar a la página|पृष्ठ में फ़िट|Ajuster à la page
Prev|Anterior|पिछला|Précédente
Next|Siguiente|अगला|Suivante
Drawing Editor|Editor de dibujo|चित्र संपादक|Éditeur de dessin
Draw Answer|Dibujar respuesta|चित्र में उत्तर दें|Dessiner une réponse
Edit Drawing|Editar dibujo|चित्र संपादित करें|Modifier le dessin
Replace|Reemplazar|बदलें|Remplacer
Upload Image|Subir imagen|चित्र अपलोड करें|Importer une image
Upload Drawing|Subir dibujo|चित्र अपलोड करें|Importer un dessin
Drawing saved|Dibujo guardado|चित्र सहेजा गया|Dessin enregistré
No drawing yet|Aún no hay dibujo|अभी कोई चित्र नहीं|Aucun dessin pour le moment
No drawing|Sin dibujo|कोई चित्र नहीं|Aucun dessin
Notes for examiner (optional)|Notas para el examinador (opcional)|परीक्षक के लिए नोट्स (वैकल्पिक)|Notes pour le correcteur (facultatif)
Enter your answer...|Escribe tu respuesta...|अपना उत्तर लिखें...|Saisissez votre réponse...
Pen|Lápiz|कलम|Stylo
Eraser|Borrador|रबर|Gomme
Line|Línea|रेखा|Ligne
Rectangle|Rectángulo|आयत|Rectangle
Ellipse|Elipse|दीर्घवृत्त|Ellipse
Triangle|Triángulo|त्रिभुज|Triangle
Arrow|Flecha|तीर|Flèche
Width|Grosor|मोटाई|Épaisseur
Ink Color|Color de tinta|स्याही का रंग|Couleur d’encre
Guides|Guías|मार्गदर्शक|Guides
Undo|Deshacer|पूर्ववत करें|Annuler
Redo|Rehacer|फिर करें|Rétablir
Ruler|Regla|मापनी|Règle
Protractor|Transportador|कोणमापक|Rapporteur
Zoom|Zoom|ज़ूम|Zoom
Done|Listo|पूर्ण|Terminé
Save / Done|Guardar / Listo|सहेजें / पूर्ण|Enregistrer / Terminé
Drawing Answer|Respuesta dibujada|चित्र उत्तर|Réponse dessinée
Custom color…|Color personalizado…|कस्टम रंग…|Couleur personnalisée…
Reset zoom|Restablecer zoom|ज़ूम रीसेट करें|Réinitialiser le zoom
Reset guide positions|Restablecer posiciones de las guías|मार्गदर्शक स्थान रीसेट करें|Replacer les guides
Space + drag to pan|Espacio + arrastrar para desplazar|पैन करने के लिए स्पेस + खींचें|Espace + glisser pour déplacer
pinch to zoom|pellizcar para hacer zoom|ज़ूम करने के लिए पिंच करें|pincer pour zoomer
Cancel|Cancelar|रद्द करें|Annuler
Close|Cerrar|बंद करें|Fermer
Yes|Sí|हाँ|Oui
No|No|नहीं|Non
OK|Aceptar|ठीक है|OK
Clear drawing|Borrar dibujo|चित्र साफ़ करें|Effacer le dessin
Remove this drawing from your answer?|¿Eliminar este dibujo de tu respuesta?|इस चित्र को उत्तर से हटाएँ?|Supprimer ce dessin de votre réponse ?
Clear the ink on this canvas? You can undo this action.|¿Borrar la tinta del lienzo? Puedes deshacerlo.|इस कैनवास की स्याही मिटाएँ? आप इसे पूर्ववत कर सकते हैं।|Effacer l’encre de ce canevas ? Vous pourrez annuler cette action.
Ready to finish?|¿Todo listo para terminar?|समाप्त करने के लिए तैयार हैं?|Prêt à terminer ?
Keep working|Seguir trabajando|काम जारी रखें|Continuer à travailler
Review answers|Revisar respuestas|उत्तर देखें|Revoir les réponses
Practice completed|Práctica terminada|अभ्यास पूरा हुआ|Entraînement terminé
Exam completed|Examen terminado|परीक्षा पूरी हुई|Examen terminé
Attempt completed · answers locked|Intento terminado · respuestas bloqueadas|प्रयास पूरा · उत्तर लॉक हैं|Tentative terminée · réponses verrouillées
Elapsed|Tiempo transcurrido|बीता समय|Temps écoulé
Time remaining|Tiempo restante|शेष समय|Temps restant
Assisted practice|Práctica asistida|सहायता प्राप्त अभ्यास|Entraînement assisté
Save and close|Guardar y cerrar|सहेजें और बंद करें|Enregistrer et fermer
Save & Close|Guardar y cerrar|सहेजें और बंद करें|Enregistrer et fermer
Copy|Copiar|कॉपी करें|Copier
Cut|Cortar|काटें|Couper
Paste|Pegar|पेस्ट करें|Coller
Select All|Seleccionar todo|सभी चुनें|Tout sélectionner
Reset|Restablecer|रीसेट|Réinitialiser
Reset guides|Restablecer guías|मार्गदर्शक रीसेट करें|Réinitialiser les guides
Reset protractor position|Restablecer transportador|कोणमापक रीसेट करें|Replacer le rapporteur
Edit drawing answer|Editar respuesta dibujada|चित्र उत्तर संपादित करें|Modifier la réponse dessinée
Upload drawing image…|Subir imagen del dibujo…|उत्तर का चित्र अपलोड करें…|Importer une image de réponse…
Select drawing tool|Seleccionar herramienta de dibujo|चित्र उपकरण चुनें|Choisir un outil de dessin
Save and return to your answer|Guardar y volver a tu respuesta|सहेजें और उत्तर पर लौटें|Enregistrer et revenir à votre réponse
Question {qid}|Pregunta {qid}|प्रश्न {qid}|Question {qid}
Page {page}|Página {page}|पृष्ठ {page}|Page {page}
Answered {count} / {total}|Respondidas {count} / {total}|उत्तर दिए {count} / {total}|Répondues {count} / {total}
Unanswered {count}|Sin responder {count}|अनुत्तरित {count}|Sans réponse {count}
Flagged {count}|Marcadas {count}|चिह्नित {count}|Signalées {count}
{count}/{total} answered|{count}/{total} respondidas|{count}/{total} उत्तर दिए|{count}/{total} répondues
{count} found|{count} encontrados|{count} मिले|{count} trouvés
{count} documents in {groups} groups|{count} documentos en {groups} grupos|{groups} समूहों में {count} दस्तावेज़|{count} documents dans {groups} groupes
Time used {time}|Tiempo usado {time}|लगा समय {time}|Temps utilisé {time}
Paused {count} times|En pausa {count} veces|{count} बार रोका गया|Mis en pause {count} fois
Build Version: {version}|Versión: {version}|बिल्ड संस्करण: {version}|Version : {version}
Paper tools|Herramientas de examen|प्रश्नपत्र उपकरण|Outils pour les sujets
Starting Studio|Iniciando Studio|Studio शुरू हो रहा है|Démarrage de Studio
Loading preferences|Cargando preferencias|प्राथमिकताएँ लोड हो रही हैं|Chargement des préférences
Preparing workspace|Preparando el espacio de trabajo|कार्यक्षेत्र तैयार हो रहा है|Préparation de l’espace de travail
Loading subjects|Cargando asignaturas|विषय लोड हो रहे हैं|Chargement des matières
'''

CATALOGS = {language: {} for language in ('es', 'hi', 'fr')}
for _row in _ROWS.strip().splitlines():
    _source, *_translations = _row.split('|')
    if len(_translations) != 3 or any(not text for text in _translations):
        raise ValueError(f'Invalid interface translation: {_source}')
    for _language, _text in zip(CATALOGS, _translations):
        CATALOGS[_language][_source] = _text
