from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json
import requests
import os
import uuid
from datetime import datetime, timedelta

app = Flask(__name__)

app.secret_key = 'supersecretkey123_very_long_and_random_string_for_production' 

API_KEY = "052440f4a709b515cd2b46ca2c79b4f8"

#Вспомогательные функции для работы с данными
def safe_load_data(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        save_data(filename, {})
        return {}


def save_data(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# Загрузка данных при старте приложения
users = safe_load_data('data/users.json')
threads = safe_load_data('data/threads.json')



def calculate_user_stats(username):
    user_data = users.get(username)
    if not user_data:
        return
    total_xp = 0

    # XP за регистрацию (единоразово)
    if user_data.get('join_date'):
        total_xp += 50

    # XP за закладки
    bookmarks = user_data.get('bookmarks', {})
    total_xp += len(bookmarks.get('Просмотрено', [])) * 10
    total_xp += len(bookmarks.get('Любимые', [])) * 15

    # XP за комментарии к фильмам
    total_xp += len(user_data.get('comments', [])) * 3

    # XP за коллекции
    collections = user_data.get('collections', [])
    total_xp += len(collections) * 15
    for col in collections:
        total_xp += len(col.get('movies', [])) * 2
        # XP за лайки на свои коллекции
        likes_on_this_collection = sum(1 for u_data in users.values() if col['id'] in u_data.get('liked_collections', []))
        total_xp += likes_on_this_collection * 1

    # XP за комментарии к коллекциям
    total_xp += len(user_data.get('collection_comments', [])) * 4

    # XP за треды и комментарии в тредах
    for thread_id, thread_info in threads.items():
        if thread_info.get('created_by') == username:
            total_xp += 20
        for comment in thread_info.get('comments', []):
            if comment.get('user') == username:
                total_xp += 5

    # XP за друзей
    total_xp += len(user_data.get('friends', [])) * 10

    # XP за оценки фильмов по категориям
    movie_ratings = user_data.get('movie_ratings', {})
    for tmdb_id, ratings_data in movie_ratings.items():
        # Каждая категория дает 1 XP, максимум 5 XP за фильм
        total_xp += sum(1 for category, rating_value in ratings_data.items() if rating_value > 0)
    user_data['total_xp'] = total_xp

     # Расчет уровня и прогресса
    level = 1
    xp_thresholds = {1: 0} # XP, необходимое для достижения уровня
    for i in range(1, 11): # Рассчитаем пороги до 10 уровня
        xp_thresholds[i+1] = xp_thresholds[i] + (i * 50 + i**2 * 5) # XP для перехода на следующий уровень
    level = 1
    for lvl, threshold_xp in xp_thresholds.items():
        if total_xp >= threshold_xp:
            level = lvl
        else:
            break

    xp_for_current_level_start = xp_thresholds.get(level, 0)
    xp_for_next_level_start = xp_thresholds.get(level + 1, total_xp + 1) # Если это последний уровень, то нет следующего порога
    user_data['level'] = level
    user_data['xp_to_next_level'] = xp_for_next_level_start - total_xp if total_xp < xp_for_next_level_start else 0
    
    # Прогресс должен быть относительно XP, набранного в текущем уровне, к XP, необходимому для текущего уровня
    xp_in_current_level = total_xp - xp_for_current_level_start
    xp_needed_for_current_level = xp_for_next_level_start - xp_for_current_level_start
    user_data['level_progress'] = int((xp_in_current_level / xp_needed_for_current_level) * 100) if xp_needed_for_current_level > 0 else 100

    if user_data['level_progress'] > 100:
        user_data['level_progress'] = 100

    titles = {
            1: "Новичок",
            2: "Энтузиаст",
            3: "Исследователь",
            4: "Знаток",
            5: "Киноман",
            6: "Коллекционер",
            7: "Обсуждающий",
            8: "Социальный деятель",
            9: "Мастер Moovly",
            10: "Легенда Moovly"
        }
    user_data['title'] = titles.get(level, f"Уровень {level}") # Если уровень выше 10, просто отображаем уровень

    check_achievements(username)
    users[username] = user_data
    save_data('data/users.json', users)

def prepare_bookmarks(bookmarks_raw):
    mapping = {
        'Смотрю': 'watching',
        'Буду смотреть': 'plan',
        'Брошено': 'dropped',
        'Просмотрено': 'watched',
        'Любимые': 'favorites'
    }
    english = {eng: bookmarks_raw.get(rus, []) for rus, eng in mapping.items()}
    for key in mapping.values():
        if key not in english:
            english[key] = []
    return english


def check_achievements(username):
    user_data = users.get(username)
    if not user_data:
        return

    # Инициализация достижений, если их нет или они неполные
    default_achievements = [
        {
            'name': 'Новичок',
            'description': 'Зарегистрировался на сайте',
            'criteria': 'Создать аккаунт',
            'earned': False,
            'icon': 'fa-user-plus',
            'emoji': '👶',
            'color': 'from-blue-400 to-blue-600',
            'color_start': '#60a5fa',
            'color_end': '#2563eb'
        },
        {
            'name': 'Киноман',
            'description': 'Посмотреть 50 фильмов',
            'criteria': 'Добавить 50 фильмов в "Просмотрено"',
            'earned': False,
            'icon': 'fa-film',
            'emoji': '🎬',
            'color': 'from-purple-400 to-purple-600',
            'color_start': '#a78bfa',
            'color_end': '#7c3aed' 
        },
        {
            'name': 'Комментатор',
            'description': 'Оставить 10 комментариев',
            'criteria': 'Оставить 10 комментариев к фильмам',
            'earned': False,
            'icon': 'fa-comments',
            'emoji': '💬',
            'color': 'from-green-400 to-green-600',
            'color_start': '#4ade80',
            'color_end': '#16a34a'
        },
        {
            'name': 'Коллекционер',
            'description': 'Создать 5 коллекций',
            'criteria': 'Создать 5 коллекций фильмов',
            'earned': False,
            'icon': 'fa-boxes',
            'emoji': '📦',
            'color': 'from-red-400 to-red-600',
            'color_start': '#f87171',
            'color_end': '#dc2626'
        },
        {
            'name': 'Популярный коллекционер',
            'description': 'Получить 50 лайков на свои коллекции',
            'criteria': 'Суммарно получить 50 лайков на свои коллекции',
            'earned': False,
            'icon': 'fa-star',
            'emoji': '⭐',
            'color': 'from-pink-400 to-pink-600',
            'color_start': '#f472b6',
            'color_end': '#db2777'
        },
        {
            'name': 'Социальная бабочка',
            'description': 'Добавить 10 друзей',
            'criteria': 'Иметь 10 друзей',
            'earned': False,
            'icon': 'fa-user-group',
            'emoji': '🤝',
            'color': 'from-indigo-400 to-indigo-600',
            'color_start': '#818cf8',
            'color_end': '#4f46e5'
        },
        {
            'name': 'Активный участник',
            'description': 'Оставить 50 комментариев в тредах',
            'criteria': 'Оставить 50 комментариев в тредах обсуждений',
            'earned': False,
            'icon': 'fa-comment-dots',
            'emoji': '🗣️',
            'color': 'from-teal-400 to-teal-600',
            'color_start': '#2dd4bf',
            'color_end': '#0d9488'
        },
        {
            'name': 'Оценщик',
            'description': 'Оценить 20 фильмов по категориям',
            'criteria': 'Оценить 20 уникальных фильмов по категориям (сюжет, актерская игра и т.д.)',
            'earned': False,
            'icon': 'fa-sliders',
            'emoji': '📊',
            'color': 'from-orange-400 to-orange-600',
            'color_start': '#fb923c',
            'color_end': '#ea580c'
        }
    ]

    # Обновляет достижения пользователя, добавляя новые, если они появились
    current_achievements = {a['name']: a for a in user_data.get('achievements', [])}
    updated_achievements = []

    for default_ach in default_achievements:
        if default_ach['name'] in current_achievements:
            existing_ach = current_achievements[default_ach['name']]
            default_ach['earned'] = existing_ach.get('earned', False)
        updated_achievements.append(default_ach)

    user_data['achievements'] = updated_achievements

    watched_count = len(user_data.get('bookmarks', {}).get('Просмотрено', []))
    comment_count = len(user_data.get('comments', []))
    collection_count = len(user_data.get('collections', []))
    friends_count = len(user_data.get('friends', []))

    # Подсчет лайков на коллекции
    total_collection_likes = 0
    for col in user_data.get('collections', []):
        total_collection_likes += sum(1 for u_data in users.values() if col['id'] in u_data.get('liked_collections', []))

    # Подсчет комментариев в тредах
    thread_comments_count = 0
    for thread_id, thread_info in threads.items():
        for comment in thread_info.get('comments', []):
            if comment.get('user') == username:
                thread_comments_count += 1

    # Подсчет оцененных фильмов
    rated_movies_count = len(user_data.get('movie_ratings', {}))
    
    # Проверет и обновляет статус достижений
    for achievement in user_data['achievements']:
        if achievement['name'] == 'Новичок' and not achievement['earned']:
            pass

        elif achievement['name'] == 'Киноман' and not achievement['earned']:
            if watched_count >= 50:
                achievement['earned'] = True
                flash('Поздравляем! Вы получили достижение "Киноман"', 'success')
        elif achievement['name'] == 'Комментатор' and not achievement['earned']:
            if comment_count >= 10:
                achievement['earned'] = True
                flash('Поздравляем! Вы получили достижение "Комментатор"', 'success')
        elif achievement['name'] == 'Коллекционер' and not achievement['earned']:
            if collection_count >= 5:
                achievement['earned'] = True
                flash('Поздравляем! Вы получили достижение "Коллекционер"', 'success')
        elif achievement['name'] == 'Популярный коллекционер' and not achievement['earned']:
                if total_collection_likes >= 50:
                    achievement['earned'] = True
                    flash('Поздравляем! Вы получили достижение "Популярный коллекционер"', 'success')
        elif achievement['name'] == 'Социальная бабочка' and not achievement['earned']:
            if friends_count >= 10:
                achievement['earned'] = True
                flash('Поздравляем! Вы получили достижение "Социальная бабочка"', 'success')
        elif achievement['name'] == 'Активный участник' and not achievement['earned']:
            if thread_comments_count >= 50:
                achievement['earned'] = True
                flash('Поздравляем! Вы получили достижение "Активный участник"', 'success')
        elif achievement['name'] == 'Оценщик' and not achievement['earned']:
            if rated_movies_count >= 20:
                achievement['earned'] = True
                flash('Поздравляем! Вы получили достижение "Оценщик"', 'success')

    users[username] = user_data
    save_data('data/users.json', users)


def get_top_active_users_by_xp(limit=10):
    week_ago = datetime.now() - timedelta(days=7)
    top_users = []
    
    for username, user_data in users.items():
        calculate_user_stats(username) 
        
        # Получает обновленные данные пользователя
        user_data = users.get(username) 
        
        total_xp = user_data.get('total_xp', 0)
        level = user_data.get('level', 1)
        title = user_data.get('title', 'Новичок')

        # Если у пользователя есть XP и он активен за последнюю неделю
        if total_xp > 0:
            top_users.append({
                'username': username,
                'total_xp': total_xp,
                'avatar': user_data.get('avatar', '/static/default_avatar.jpg'),
                'level': level,
                'title': title
            })
    
    # Сортирует по убыванию XP
    top_users.sort(key=lambda x: x['total_xp'], reverse=True)
    
    return top_users[:limit]




#Функции для работы с TMDB API
def get_movie_data(movie_id):
    try:
        details_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
        credits_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits"
        
        params = {
            "api_key": API_KEY,
            "language": "ru-RU"
            }
        
        details_resp = requests.get(details_url, params=params)
        credits_resp = requests.get(credits_url, params=params)
        
        actors = []
        genres = []
        title = ""
        poster_path = ""
        overview = ""
        release_date = ""
        vote_average = 0.0
        
        if details_resp.status_code == 200:
            details = details_resp.json()
            genres = [genre["name"] for genre in details.get("genres", [])]
            title = details.get("title", "")
            poster_path = details.get("poster_path", "")
            overview = details.get("overview", "")
            release_date = details.get("release_date", "")
            vote_average = details.get("vote_average", 0.0)
        
        if credits_resp.status_code == 200:
            actors = [actor["name"] for actor in credits_resp.json().get("cast", [])[:5]]
        
        return actors, genres, title, poster_path, overview, release_date, vote_average
    
    except Exception as e:
        print(f"Error in get_movie_data for movie {movie_id}: {str(e)}")
        return [], [], "", "", "", "", 0.0

def get_pop_movies():
    try:
        url = "https://api.themoviedb.org/3/trending/movie/week"
        params = {
            "api_key": API_KEY,
            "language": "ru-RU",
            "page": 1,
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        movies_data = response.json().get("results", [])[:12]
        if not movies_data:
            print("В ")
            return []

        movies = []
        for movie in movies_data:
            movie_id = movie.get("id")
            if not movie_id:
                continue

            actors, genres, title, poster_path, overview, release_date, vote_average = get_movie_data(movie_id)

            movies.append({
                "id": movie_id,
                "title": title,
                "poster_path": poster_path,
                "overview": overview,
                "release_date": release_date,
                "vote_average": vote_average,
                "actors": actors,
                "genres": genres,
                "media_type": movie.get("media_type", "movie")
            })
        
        return movies

    except requests.exceptions.RequestException as e:
        print(f"Error fetching popular movies from TMDB: {str(e)}")
        return []
    except Exception as e:
        print(f"Unexpected error in get_pop_movies: {str(e)}")
        return []

# --- Функции для работы с данными пользователя ---
def get_comments_for_title(tmdb_id):
    """Получает комментарии для конкретного фильма по tmdb_id."""
    comments = []
    for username, user_info in users.items():
        user_comments = user_info.get('comments', [])
        for comment in user_comments:
            if comment.get('tmdb_id') == tmdb_id:
                comments.append({
                    "user": username,
                    "text": comment.get("text", ""),
                    "timestamp": comment.get("timestamp", "")
                })
    comments.sort(key=lambda x: datetime.strptime(x['timestamp'], "%Y-%m-%d %H:%M:%S"), reverse=True)
    return comments




# --- Контекстный процессор для шаблонов ---
@app.context_processor
def inject_user():
    current_user_data = None
    if 'username' in session:
        username = session['username']
        current_user_data = users.get(username)

        if current_user_data:
            # Можно вызывать подсчёт статистики или достижений
            calculate_user_stats(username)
            current_user_data.setdefault('username', username)

    return dict(
        user_authenticated=bool(current_user_data),
        current_user=current_user_data,
        user=current_user_data
    )


# --- Фильтры шаблонов ---
@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d.%m.%Y'):
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return value
    return value.strftime(format)


# --- Маршруты приложения ---
@app.route('/')
def index():
    movies = get_pop_movies()
    top_active_users = get_top_active_users_by_xp(limit=10)
    user = session.get('user')  # Предполагается, что данные о пользователе хранятся в сессии
    user_authenticated = 'username' in session  # Проверяем, вошел ли пользователь в систему
    return render_template('index.html', 
                           movies=movies or [], 
                           top_active_users=top_active_users, 
                           user=user, 
                           user_authenticated=user_authenticated)



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash("Заполните все поля!", "error")
            return redirect(url_for('register'))
        
        if username in users:   
            flash("Пользователь с таким именем уже существует.", "error")
            return redirect(url_for('register'))
        
        # Инициализация нового пользователя с полным набором полей
        users[username] = {
            "uername": username,
            "password": password,
            "join_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "last_login": datetime.now().strftime("%d %B %Y %H:%M"),
            "avatar": "/static/default_avatar.jpg",
            "bio": "",
            "location": "",
            "social_links": [],
            "bookmarks": {
                "Смотрю": [],
                "Буду смотреть": [],
                "Брошено": [],
                "Просмотрено": [],
                "Любимые": []
            },
            "collections": [],
            "comments": [],
            "collection_comments": [], # Для комментариев к коллекциям
            "activity": [],
            "achievements": [], # Будет инициализировано check_achievements
            "liked_collections": [],
            "friends": [],
            "friend_requests": [],
            "friend_requests_sent": []
        }
    
        
        # Выдаем достижение "Новичок"
        check_achievements(username) # Вызываем для инициализации и проверки достиженийe
        
        save_data('data/users.json', users)
        session['username'] = username
        flash("Регистрация прошла успешно!", "success")
        return redirect(url_for('index'))
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_data = users.get(username)
        
        if user_data and user_data['password'] == password: # В реальном приложении - проверка хеша
            session['username'] = username
            user_data['last_login'] = datetime.now().strftime("%d %B %Y %H:%M")
            save_data('data/users.json', users)
            flash("Вы успешно вошли!", "success")
            return redirect(url_for('index'))
        else:
            flash("Неверное имя пользователя или пароль.", "error")
            return redirect(url_for('login'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash("Вы вышли из аккаунта.", "info")
    return redirect(url_for('index'))



@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not session.get('username'):
        flash("Необходимо войти в аккаунт для просмотра профиля.", "info")
        return redirect(url_for('login'))

    username = session['username']
    user_data = users.get(username, {}) # Получаем актуальные данные

    if request.method == 'POST':
        new_username = request.form.get('username')
        new_bio = request.form.get('bio')
        new_location = request.form.get('location')
        avatar_file = request.files.get('avatar')
        if avatar_file and avatar_file.filename != '':
            ext = os.path.splitext(avatar_file.filename)[1]
            if ext.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                flash('Недопустимый формат изображения.', 'error')
                return redirect(url_for('profile'))
    
            filename = f"{username}_avatar{ext}"
            filepath = os.path.join('static', 'avatars', filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            avatar_file.save(filepath)

            user_data['avatar'] = f"/static/avatars/{filename}"

        # Обработка смены имени пользователя
        if new_username and new_username != username:
            if new_username in users:
                flash("Имя пользователя уже занято.", "error")
            else:
                # Обновляем ключ в users и сессии
                users[new_username] = users.pop(username)
                session['username'] = new_username
                username = new_username # Обновляем для текущего запроса
                flash("Имя пользователя успешно изменено!", "success")
                user_data = users.get(username) # Обновляем user_data после смены имени

        # Обновление био и местоположения
        user_data['bio'] = new_bio
        user_data['location'] = new_location
        
        save_data('data/users.json', users)
        flash("Профиль успешно обновлен!", "success")
        return redirect(url_for('profile'))
    
    # Подсчет статистики
    comment_count = len(user_data.get('comments', []))
    collection_count = len(user_data.get('collections', []))
    
    # Для подсчета фильмов/сериалов в "Просмотрено"
    watched_movies_count = len([item for item in user_data.get('bookmarks', {}).get('Просмотрено', []) if item.get('type') == 'movie'])
    watched_series_count = len([item for item in user_data.get('bookmarks', {}).get('Просмотрено', []) if item.get('type') == 'series'])


    bookmarks_eng = prepare_bookmarks(user_data.get('bookmarks', {}))

    # Фильтрация активности
    activity_filter = request.args.get('activity_filter', 'all')
    filtered_activity = []
    all_activity = user_data.get('activity', [])
    
    if activity_filter == 'all':
        filtered_activity = all_activity
    elif activity_filter == 'comments':
        filtered_activity = [a for a in all_activity if a.get('type') == 'comment']
    elif activity_filter == 'collections':
        filtered_activity = [a for a in all_activity if a.get('type') == 'collection' or a.get('type') == 'collection_add_movie']
    elif activity_filter == 'bookmark':
        filtered_activity = [a for a in all_activity if a.get('type') == 'bookmark']

    # Сортировка активности по времени (от новой к старой)
    filtered_activity.sort(key=lambda x: datetime.strptime(x['time'], '%Y-%m-%d %H:%M:%S'), reverse=True)

    now = datetime.now()

    activity_this_month = [
        a for a in user_data.get('activity', [])
        if a.get('time') and a['time'].startswith(now.strftime('%Y-%m'))
    ]

    # Получаем список входящих запросов в друзья
    friend_requests = user_data.get('friend_requests', [])
    # Получаем список друзей
    friends_list = user_data.get('friends', [])

    return render_template(
        "profile.html",
        user={
            'username': username,
            'join_date': user_data.get('join_date', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            'avatar': user_data.get('avatar', '/static/default_avatar.jpg'),
            'is_verified': user_data.get('is_verified', False),
            'is_premium': user_data.get('is_premium', False),
            'location': user_data.get('location', 'Не указано'),
            'bio': user_data.get('bio', 'Этот пользователь пока не добавил информацию о себе'),
            'badges': user_data.get('achievements', []),
            'badges_total': len([a for a in user_data.get('achievements', []) if a.get('earned')]),
            'activity': filtered_activity,
            'collections': user_data.get('collections', []),
            'comments_count': comment_count,
            'collections_count': collection_count,
            'movies_count': watched_movies_count,
            'shows_count': watched_series_count,
            'level': user_data.get('level', 1),
            'level_progress': user_data.get('level_progress', 0),
            'total_xp': user_data.get('total_xp', 0),
            'xp_to_next_level': user_data.get('xp_to_next_level', 0),
            'title': user_data.get('title', 'Новичок'),
            'friends': friends_list, # Передаем список друзей
            'friend_requests': friend_requests, # Передаем входящие запросы
            'social_links': user_data.get('social_links', [])   
        },
        bookmarks=bookmarks_eng,
        base_image_url="https://image.tmdb.org/t/p/w500",
        activity_filter=activity_filter,
        now=now,
        activity_this_month=activity_this_month
    )


@app.route('/user/<username>')
def user_profile(username):
    if 'username' in session and session['username'] == username:
        return redirect(url_for('profile'))

    profile_user_data = users.get(username)
    if not profile_user_data:
        flash("Пользователь не найден.", "error")
        return redirect(url_for('index'))

    current_user_session = session.get('username') 
    
    is_friend = False
    friend_request_sent = False
    
    if current_user_session:
        current_user_data = users.get(current_user_session, {})
        is_friend = username in current_user_data.get('friends', [])
        friend_request_sent = username in current_user_data.get('friend_requests_sent', [])
    
    # Фильтрация коллекций: показываем только публичные или свои
    display_collections = []
    for col in profile_user_data.get('collections', []):
        if not col.get('is_private', False) or current_user_session == username:
            display_collections.append(col)

    # Фильтрация достижений: показываем только заработанные
    earned_achievements = [ach for ach in profile_user_data.get('achievements', []) if ach.get('earned')]

    # Фильтрация активности: показываем только публичную активность или всю, если это свой профиль
    display_activity = []
    if current_user_session == username:
        display_activity = profile_user_data.get('activity', [])
    else:
        # Пока показываем всю, если нет явного флага приватности в activity
        display_activity = profile_user_data.get('activity', []) 

    display_activity.sort(key=lambda x: datetime.strptime(x['time'], '%Y-%m-%d %H:%M:%S'), reverse=True)

    return render_template('user_profile.html',
                         profile_user=profile_user_data,
                         username=username,
                         is_friend=is_friend,
                         friend_request_sent=friend_request_sent,
                         current_user=current_user_session, # Передаем имя текущего пользователя
                         display_collections=display_collections,
                         earned_achievements=earned_achievements,
                         display_activity=display_activity)





@app.route('/send_friend_request/<target_username>', methods=['POST'])
def send_friend_request(target_username):
    if 'username' not in session:
        flash("Необходимо войти в аккаунт, чтобы отправлять запросы в друзья.", "warning")
        return redirect(url_for('login'))

    current_username = session['username']
    if current_username == target_username:
        flash("Вы не можете отправить запрос в друзья самому себе.", "error")
        return redirect(url_for('user_profile', username=target_username))

    current_user_data = users.get(current_username)
    target_user_data = users.get(target_username)

    if not target_user_data:
        flash("Пользователь не найден.", "error")
        return redirect(url_for('index'))

    # Проверяем, не друзья ли уже
    if target_username in current_user_data.get('friends', []):
        flash(f"Вы уже друзья с {target_username}.", "info")
        return redirect(url_for('user_profile', username=target_username))

    # Проверяем, не отправлен ли уже запрос
    if target_username in current_user_data.get('friend_requests_sent', []):
        flash(f"Запрос в друзья уже отправлен {target_username}.", "info")
        return redirect(url_for('user_profile', username=target_username))

    # Проверяем, не пришел ли уже запрос от этого пользователя
    if current_username in target_user_data.get('friend_requests', []):
        # Если запрос уже пришел, то это взаимный запрос, можно сразу добавить в друзья
        current_user_data.setdefault('friends', []).append(target_username)
        target_user_data.setdefault('friends', []).append(current_username)
        target_user_data['friend_requests'].remove(current_username) # Удаляем входящий запрос
        flash(f"Вы и {target_username} теперь друзья!", "success")
    else:
        # Отправляем новый запрос
        current_user_data.setdefault('friend_requests_sent', []).append(target_username)
        target_user_data.setdefault('friend_requests', []).append(current_username)
        flash(f"Запрос в друзья отправлен {target_username}.", "success")
    
    save_data('data/users.json', users)
    return redirect(url_for('user_profile', username=target_username))


@app.route('/accept_friend_request/<requester>', methods=['POST'])
def accept_friend_request(requester):
    if 'username' not in session:
        flash("Необходимо войти в аккаунт.", "warning")
        return redirect(url_for('login'))

    username = session['username']
    user_data = users.get(username)
    requester_data = users.get(requester)

    if not user_data or requester not in user_data.get('friend_requests',  []):
        flash("Запрос не найден.", "error")
        return redirect(url_for('profile'))
    
    if 'friends' not in user_data:
        user_data['friends'] = []
    if 'friends' not in requester_data:
        requester_data['friends'] = []

    # Добавляем в друзья
    user_data['friends'].append(requester)
    requester_data['friends'].append(username)

    # Удаляем запрос из входящих у текущего пользователя
    user_data['friend_requests'].remove(requester)

    if username in requester_data.get('friend_requests_sent', []):
        requester_data['friend_requests_sent'].remove(username)

    save_data('data/users.json', users)
    flash(f"Вы приняли запрос от {requester}.", "success")
    return redirect(url_for('profile'))


@app.route('/decline_friend_request/<requester>', methods=['POST'])
def decline_friend_request(requester):
    if 'username' not in session:
        flash("Необходимо войти в аккаунт.", "warning")
        return redirect(url_for('login'))

    username = session['username']
    user_data = users.get(username)
    requester_data = users.get(requester)

    if not user_data or requester not in user_data['friend_requests']:
        flash("Запрос не найден.", "error")
        return redirect(url_for('profile'))

    # Удаляем запрос
    user_data['friend_requests'].remove(requester)
    if username in requester_data.get('friend_requests_sent', []):
        requester_data['friend_requests_sent'].remove(username)

    save_data('data/users.json', users)
    flash(f"Вы отклонили запрос от {requester}.", "success")
    return redirect(url_for('profile'))



@app.route('/movie/<int:tmdb_id>')
def movie_detail(tmdb_id):
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    params = {
        "api_key": API_KEY,
        "language": "ru-RU",
        "append_to_response": "videos,credits"
    }
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        flash("Не удалось загрузить данные о фильме.", "error")
        return redirect(url_for("index"))

    data = response.json()

    # Получаем информацию о режиссере
    director = next((crew_member.get('name') for crew_member in data.get('credits', {}).get('crew', []) if crew_member.get('job') == 'Director'), '')

    # Получаем ключ трейлера
    trailer_key = next((video.get('key') for video in data.get('videos', {}).get('results', []) if video.get('type') == 'Trailer' and video.get('site') == 'YouTube'), '')

    # Получаем данные о фильме
    actors = [actor['name'] for actor in data.get('credits', {}).get('cast', [])]
    genres = [genre['name'] for genre in data.get('genres', [])]
    title = data.get('title', 'N/A')
    poster_path = data.get('poster_path', '')
    overview = data.get('overview', 'Нет описания')
    release_date = data.get('release_date', '')
    vote_average = data.get('vote_average', None)

    # Получаем комментарии
    comments = get_comments_for_title(tmdb_id)

    return render_template(
        "moviepage.html",
        tmdb_id=tmdb_id,
        title=title,
        release_year=release_date[:4] if release_date else 'N/A',
        description=overview,
        genres=genres,
        poster_url=f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else '',
        director=director,
        trailer_url=f"https://www.youtube.com/embed/{trailer_key}" if trailer_key else '',
        comments=comments,
        actors=actors,
        vote_average=round(vote_average, 1) if vote_average is not None else 'N/A'
    )


@app.route('/add_comment/<int:tmdb_id>', methods=['POST'])
def add_comment(tmdb_id):
    if not session.get('username'):
        flash("Для добавления комментария необходимо войти в аккаунт.", "warning")
        return redirect(url_for('login'))
    
    username = session['username']
    comment_text = request.form.get('comment_text')
    
    if not comment_text:
        flash("Комментарий не может быть пустым.", "error")
        return redirect(url_for('movie_detail', tmdb_id=tmdb_id))
    
    user_data = users.get(username)
    if not user_data:
        flash("Пользователь не найден.", "error")
        return redirect(url_for('login'))

    user_data.setdefault('comments', [])
    
    new_comment = {
        "tmdb_id": tmdb_id,
        "text": comment_text,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    user_data['comments'].append(new_comment)
    
    # Получаем данные фильма для активности
    actors, genres, title, poster_path, overview, release_date, vote_average = get_movie_data(tmdb_id)
    user_data.setdefault('activity', []).append({
        'type': 'comment',
        'text': f'оставил(а) комментарий к фильму "{title}"',
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'icon': 'fas fa-comment',
        'movie': title,
        'poster': poster_path,
        'movie_id': tmdb_id,
        'comment': comment_text
    })
    save_data('data/users.json', users)
    check_achievements(username) # Проверяем достижения после добавления комментария
    flash("Комментарий успешно добавлен!", "success")
    return redirect(url_for('movie_detail', tmdb_id=tmdb_id))


@app.route('/api/movie/<int:tmdb_id>/rate', methods=['POST'])
def rate_movie(tmdb_id):
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    ratings = {
        'plot': int(data.get('plot', 0)),
        'acting': int(data.get('acting', 0)),
        'visuals': int(data.get('visuals', 0)),
        'music': int(data.get('music', 0)),
        'direction': int(data.get('direction', 0))
    }
    username = session['username']
    users.setdefault(username, {}).setdefault('movie_ratings', {})[str(tmdb_id)] = ratings
    save_data('data/users.json', users)
    
    return jsonify({'success': True})


@app.route('/api/movie/<int:tmdb_id>/ratings')
def get_movie_ratings(tmdb_id):
    all_ratings = {
        'plot': [],
        'acting': [],
        'visuals': [],
        'music': [],
        'direction': []
    }
    
    for user_data in users.values():
        if 'movie_ratings' in user_data and str(tmdb_id) in user_data['movie_ratings']:
            for category in all_ratings:
                all_ratings[category].append(user_data['movie_ratings'][str(tmdb_id)][category])
    
    # Вычисляем средние оценки
    avg_ratings = {
        category: sum(values)/len(values) if values else 0 
        for category, values in all_ratings.items()
    }
    
    return jsonify({
        'average_ratings': avg_ratings,
        'total_votes': len(all_ratings['plot'])
    })



@app.route('/catalog')
def catalog():
    page = request.args.get('page', 1, type=int)
    genre_filter = request.args.get('genre')

    discover_url = f'https://api.themoviedb.org/3/discover/movie'
    params = {
        'api_key': API_KEY,
        'language': 'ru-RU',
        'sort_by': 'popularity.desc',
        'page': page
    }

    if genre_filter:
        params['with_genres'] = genre_filter

    response = requests.get(discover_url, params=params)
    response.raise_for_status()
    data = response.json()
    movies = data.get('results', [])

    genre_url = f'https://api.themoviedb.org/3/genre/movie/list'
    genre_response = requests.get(genre_url, params={'api_key': API_KEY, 'language': 'ru-RU'})
    genre_response.raise_for_status()
    genres_data = genre_response.json().get('genres', [])

    return render_template('catalog.html', movies=movies, genres=genres_data, selected_genre=genre_filter, page=page)


@app.route('/api/search/movies')
def search_movies():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify([])

    url = "https://api.themoviedb.org/3/search/movie"
    params = {
        'api_key': API_KEY,
        'language': 'ru-RU',
        'query': query,
        'page': 1,
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Проверка на ошибки HTTP
        results = response.json().get('results', [])
        
        # Форматируем ответ для фронтенда
        movies = [{
            'id': m['id'],
            'title': m.get('title', 'Без названия'),
            'poster_path': m.get('poster_path'),
            'release_date': m.get('release_date', 'N/A')[:4]  # Год выпуска
        } for m in results if m.get('poster_path')]  # Только фильмы с постерами
        
        return jsonify(movies)
    
    except requests.exceptions.RequestException as e:
        print(f"Ошибка поиска: {str(e)}")
        return jsonify({'error': 'Ошибка при поиске фильмов'}), 500
    

@app.route('/advanced-search')
def advanced_search():
    genre_url = f'https://api.themoviedb.org/3/genre/movie/list'
    current_year = datetime.now().year
    try:
        genre_response = requests.get(genre_url, params={'api_key': API_KEY, 'language': 'ru-RU'})
        genre_response.raise_for_status()
        genres = genre_response.json().get('genres', [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching genres for advanced search: {str(e)}")
        genres = [] # Возвращаем пустой список жанров в случае ошибки
    return render_template('advanced_search.html', genres=genres, current_year=current_year)


@app.route('/api/advanced-search')
def api_advanced_search():
    title_query = request.args.get("query")
    genres = request.args.get("genres") # Это будет строка "id1,id2,id3"
    year_from = request.args.get("year_from")
    year_to = request.args.get("year_to")
    rating_min = request.args.get("rating_min")
    page = request.args.get("page", 1, type=int) # Убедитесь, что page - int

    params = {
        "api_key": API_KEY,
        "language": "ru-RU",
        "page": page,
        "sort_by": "popularity.desc" # Или другой критерий сортировки по умолчанию
    }

    if genres:
        params["with_genres"] = genres # TMDB ожидает строку с ID через запятую
    if year_from:
        params["primary_release_date.gte"] = f"{year_from}-01-01"
    if year_to:
        params["primary_release_date.lte"] = f"{year_to}-12-31"
    if rating_min:
        params["vote_average.gte"] = rating_min

    # Если есть текстовый запрос, используем search/movie, иначе discover/movie
    if title_query:
        url = "https://api.themoviedb.org/3/search/movie"
        params["query"] = title_query
        # Для search/movie не все discover параметры применимы, но TMDB обычно игнорирует лишние
    else:
        url = "https://api.themoviedb.org/3/discover/movie"

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Вызовет исключение для HTTP ошибок (4xx, 5xx)
        data = response.json()

        # Важно: если вы используете search/movie, TMDB сам фильтрует по названию.
        # Если вы используете discover/movie, а потом вручную фильтруете по названию,
        # то это может быть неэффективно, так как вы сначала получаете много данных, а потом их отбрасываете.
        # Мой предложенный выше код в app.py пытается это учесть, переключаясь между search и discover.

        return jsonify(data) # Возвращаем весь объект data, включая total_pages, total_results
    except requests.exceptions.RequestException as e:
        print(f"Error in advanced search API: {str(e)}")
        return jsonify({'error': 'Ошибка при поиске фильмов', 'details': str(e)}), 500




@app.route('/collections')
def user_collections():
    if not session.get('username'):
        flash("Необходимо войти в аккаунт для просмотра коллекций.", "warning")
        return redirect(url_for('login'))
    
    username = session['username']
    user_data = users.get(username)
    if not user_data:
        flash("Пользователь не найден.", "error")
        return redirect(url_for('login'))
    
    user_collections = user_data.get('collections', [])
    
    public_collections = []
    for user_name, other_user_data in users.items():
        if user_name != username: # Исключаем текущего пользователя
            for collection in other_user_data.get('collections', []):
                if not collection.get('is_private', False):
                    collection_copy = collection.copy() # Копируем, чтобы не изменять оригинал
                    collection_copy['author'] = user_name
                    public_collections.append(collection_copy)
    
    return render_template('collections.html', 
                         user_collections=user_collections,
                         public_collections=public_collections)


@app.route('/api/collections', methods=['POST'])
def create_collection():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = session['username']
    user_data = users.get(username)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.json
    
    collection_name = data.get('name')
    if not collection_name:
        return jsonify({'error': 'Collection name is required'}), 400

    # Создаем новую коллекцию
    new_collection = {
        'id': str(uuid.uuid4()),
        'name': collection_name,
        'description': data.get('description', ''),
        'is_private': data.get('is_private', False),
        'movies': [],
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    user_data.setdefault('collections', []).append(new_collection)

    user_data.setdefault('activity', []).append({
        'type': 'collection',
        'text': f'создал(а) новую коллекцию "{new_collection["name"]}"',
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'icon': 'fas fa-folder-open',
        'collection_name': new_collection['name'],
        'collection_id': new_collection['id'] # Добавлено для ссылки в активности
    })
    save_data('data/users.json', users)
    check_achievements(username) # Проверяем достижения после создания коллекции
    
    return jsonify({'success': True, 'collection_id': new_collection['id']})


@app.route('/collection/<collection_id>')
def collection_detail(collection_id):
    collection = None
    author = None
    is_owner = session.get('username') == author
    for username, user_data in users.items():
        for col in user_data.get('collections', []):
            if col['id'] == collection_id:
                collection = col
                author = username
                break
        if collection:
            break

    if not collection:
        flash("Коллекция не найдена.", "error")
        return redirect(url_for('collections'))
    
    # Проверяем приватность
    if collection.get('is_private', False) and session.get('username') != author:
        flash("Доступ к этой коллекции запрещен.", "error")
        return redirect(url_for('collections'))

    comments = []
    # Итерируем по всем пользователям для поиска комментариев к коллекции
    for user_name, user_info in users.items():
        for comment in user_info.get('collection_comments', []):
            if comment.get('collection_id') == collection_id:
                comments.append({
                    'author': user_name, # Автор комментария
                    'text': comment.get('text'),
                    'timestamp': comment.get('timestamp')
                })
    comments.sort(key=lambda x: datetime.strptime(x['timestamp'], "%Y-%m-%d %H:%M:%S"), reverse=True)
    
    is_liked = False
    if 'username' in session:
        current_user_data = users.get(session['username'], {})
        is_liked = collection_id in current_user_data.get('liked_collections', [])

    is_owner = session.get('username') == author
    
    return render_template('collection_detail.html',
                        collection=collection,
                        author=author,
                        comments=comments,
                        is_liked=is_liked,
                        is_owner=is_owner,
                        current_user=session.get('username'),
                        likes_count=sum(
                            1 for u in users.values() if collection_id in u.get('liked_collections', [])
                        ),
                        comments_count=len(comments))
                        
@app.route('/add_to_collection', methods=['POST'])
def add_to_collection():
    if 'username' not in session:
        flash("Необходимо войти в аккаунт.", "warning")
        return redirect(url_for('login'))

    username = session['username']
    collection_id = request.form.get('collection_id') # Используем ID коллекции
    movie_id = request.form.get('movie_id')

    user_data = users.get(username)
    if not user_data:
        flash("Пользователь не найден.", "error")
        return redirect(url_for('login'))

    collections = user_data.get('collections', [])

    # Находим коллекцию по ID
    collection = next((c for c in collections if c['id'] == collection_id), None)

    if collection:
        # Проверяем, что фильма нет в коллекции
        if int(movie_id) not in [m['id'] for m in collection['movies']]:
            # Получаем данные фильма для добавления в коллекцию
            actors, genres, title, poster_path, overview, release_date, vote_average = get_movie_data(movie_id)
            
            collection['movies'].append({
                'id': int(movie_id),
                'title': title,
                'poster_path': poster_path,
                'genres': genres
            })
            
            user_data.setdefault('activity', []).append({
                'type': 'collection_add_movie',
                'text': f'добавил(а) фильм "{title}" в коллекцию "{collection.get("name", "Неизвестная коллекция")}"',
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'icon': 'fas fa-plus-square',
                'movie': title,
                'poster': poster_path,
                'movie_id': int(movie_id),
                'collection_name': collection.get("name", "Неизвестная коллекция"),
                'collection_id': collection_id
            })
            save_data('data/users.json', users)
            flash(f"Фильм '{title}' добавлен в коллекцию '{collection.get('name', 'Неизвестная коллекция')}'.", "success")
        else:
            flash("Фильм уже в этой коллекции.", "info")
    else:
        flash("Коллекция не найдена.", "error")

    return redirect(url_for('movie_detail', tmdb_id=movie_id)) # Возвращаем на страницу фильма


@app.route('/delete_collection/<collection_id>', methods=['POST'])
def delete_collection(collection_id):
    username = session.get('username')
    if not username:
        flash("Необходимо войти в аккаунт.", "error")
        return redirect(url_for('login'))
    
    user_data = users.get(username)
    if not user_data:
        flash("Пользователь не найден.", "error")
        return redirect(url_for('profile'))
    
    initial_collection_count = len(user_data.get('collections', []))
    user_data['collections'] = [c for c in user_data.get('collections', []) if c.get('id') != collection_id]
    
    if len(user_data['collections']) < initial_collection_count:
        save_data('data/users.json', users)
        flash("Коллекция успешно удалена.", "success")
    else:
        flash("Коллекция не найдена.", "error")
    return redirect(url_for('profile'))



@app.route('/api/collection/like', methods=['POST'])
def like_collection():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    collection_id = data.get('collection_id')
    
    if not collection_id:
        return jsonify({'error': 'Missing collection_id'}), 400

    # Находим коллекцию и ее автора
    target_collection = None
    collection_author = None
    for username_iter, user_data_iter in users.items():
        for col in user_data_iter.get('collections', []):
            if col['id'] == collection_id:
                target_collection = col
                collection_author = username_iter
                break
        if target_collection:
            break
    
    if not target_collection:
        return jsonify({'error': 'Collection not found'}), 404

    # Проверяем, не лайкает ли пользователь свою собственную коллекцию
    if collection_author == session['username']:
        return jsonify({'error': 'Нельзя лайкать собственную коллекцию'}), 403

    # Проверяем приватность
    if target_collection.get('is_private', False) and session.get('username') != collection_author:
        return jsonify({'error': 'Access denied to private collection'}), 403

    current_username = session['username']
    current_user_data = users.get(current_username, {})
    
    liked_collections = current_user_data.setdefault('liked_collections', [])
    
    action = ''
    if collection_id in liked_collections:
        liked_collections.remove(collection_id)
        action = 'unliked'
    else:
        liked_collections.append(collection_id)
        action = 'liked'
    
    save_data('data/users.json', users)
    
    return jsonify({'status': 'success', 'action': action})



@app.route('/collection/comment', methods=['POST'])
def add_collection_comment():
    if 'username' not in session:
        flash("Для добавления комментария необходимо войти в аккаунт.", "warning")
        return redirect(url_for('login'))
    
    collection_id = request.form.get('collection_id')
    text = request.form.get('text')
    
    if not collection_id or not text:
        flash('Пожалуйста, заполните все поля.', "error")
        return redirect(url_for('collection_detail', collection_id=collection_id))
    
    # Проверяем существование коллекции
    target_collection = None
    collection_author = None
    for username_iter, user_data_iter in users.items():
        for col in user_data_iter.get('collections', []):
            if col['id'] == collection_id:
                target_collection = col
                collection_author = username_iter
                break
        if target_collection:
            break
    
    if not target_collection:
        flash("Коллекция не найдена.", "error")
        return redirect(url_for('collections'))

    # Проверяем приватность
    if target_collection.get('is_private', False) and session.get('username') != collection_author:
        flash("Доступ к этой коллекции запрещен.", "error")
        return redirect(url_for('collections'))

    username = session['username']
    user_data = users.get(username)
    if not user_data:
        flash("Пользователь не найден.", "error")
        return redirect(url_for('login'))
    
    comment = {
        'collection_id': collection_id,
        'text': text,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    user_data.setdefault('collection_comments', []).append(comment)
    
    # Добавляем активность
    user_data.setdefault('activity', []).append({
        'type': 'collection_comment',
        'text': f'оставил(а) комментарий к коллекции "{target_collection.get("name", "Неизвестная коллекция")}"',
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'icon': 'fas fa-comment',
        'collection_id': collection_id,
        'collection_name': target_collection.get('name', 'Неизвестная коллекция')
    })
    save_data('data/users.json', users)
    
    flash('Комментарий добавлен.', "success")
    return redirect(url_for('collection_detail', collection_id=collection_id))



@app.route('/api/collections/<collection_id>/movies', methods=['POST', 'DELETE'])
def collection_movies(collection_id):
    if 'username' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    username = session['username']
    user_data = users.get(username)
    if not user_data:
        return jsonify({"error": "User not found"}), 404

    collection = next((c for c in user_data.get('collections', []) if c['id'] == collection_id), None)
    
    if not collection:
        return jsonify({"error": "Collection not found"}), 404
    
    if request.method == 'POST':
        movie_data = request.json
        if not movie_data or 'id' not in movie_data or 'title' not in movie_data:
            return jsonify({"success": False, "message": "Invalid movie data"}), 400

        if movie_data['id'] not in [m['id'] for m in collection['movies']]:
            collection['movies'].append({
                'id': movie_data['id'],
                'title': movie_data['title'],
                'poster_path': movie_data.get('poster_path'),
                'order': len(collection['movies']) + 1 # Добавляем порядок
            })
            save_data('data/users.json', users)
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": "Фильм уже в коллекции"}), 409
    
    elif request.method == 'DELETE':
        movie_id = request.json.get('movie_id')
        if not movie_id:
            return jsonify({"success": False, "message": "Movie ID is required"}), 400

        initial_len = len(collection['movies'])
        collection['movies'] = [m for m in collection['movies'] if m['id'] != movie_id]
        
        if len(collection['movies']) < initial_len:
            save_data('data/users.json', users)
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": "Фильм не найден в коллекции"}), 404



@app.route('/api/collections/<collection_id>/order', methods=['PUT'])
def update_collection_order(collection_id):
    if 'username' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    username = session['username']
    user_data = users.get(username)
    if not user_data:
        return jsonify({"error": "User not found"}), 404

    collection = next((c for c in user_data.get('collections', []) if c['id'] == collection_id), None)
    
    if not collection:
        return jsonify({"error": "Collection not found"}), 404
    
    new_order_ids = request.json.get('order')
    if not isinstance(new_order_ids, list):
        return jsonify({"success": False, "message": "Invalid order data"}), 400

    ordered_movies = []
    movie_map = {m['id']: m for m in collection['movies']}
    
    for idx, movie_id in enumerate(new_order_ids):
        if movie_id in movie_map:
            movie = movie_map[movie_id]
            movie['order'] = idx
            ordered_movies.append(movie)
            
    collection['movies'] = ordered_movies
    save_data('data/users.json', users)
    
    return jsonify({"success": True})





@app.route('/add_bookmark', methods=['POST'])
def add_bookmark():
    if 'username' not in session:
        flash("Необходимо войти в аккаунт.", "warning")
        return redirect(url_for('login'))

    username = session['username']
    movie_id = request.form.get('movie_id')
    category = request.form.get('category')
    movie_title = request.form.get('movie_title')
    movie_poster = request.form.get('movie_poster')
    
    # movie_genres приходит как JSON-строка, нужно распарсить
    try:
        movie_genres = json.loads(request.form.get('movie_genres', '[]'))
    except json.JSONDecodeError:
        movie_genres = []

    if not movie_id or not category:
        flash("Не указаны обязательные параметры для закладки.", "error")
        return redirect(url_for('index')) # Или на страницу фильма, если возможно

    user_data = users.get(username)
    if not user_data:
        flash("Пользователь не найден.", "error")
        return redirect(url_for('login'))

    bookmarks = user_data.setdefault('bookmarks', {
        'Смотрю': [], 'Буду смотреть': [], 'Брошено': [], 'Просмотрено': [], 'Любимые': []
    })

    movie_bookmark_data = {
        'id': int(movie_id),
        'title': movie_title,
        'poster_path': movie_poster,
        'genres': movie_genres,
        'type': 'movie'
    }  

    # Удаляем фильм из других категорий закладок, если он там был
    for cat in bookmarks:
        bookmarks[cat] = [item for item in bookmarks[cat] if item.get('id') != int(movie_id)]   

    # Добавляем в выбранную категорию
    if category in bookmarks:
        bookmarks[category].append(movie_bookmark_data)
    else:
        flash(f"Неизвестная категория закладок: {category}", "error")
        return redirect(url_for('movie_detail', tmdb_id=movie_id))

    # Добавляем активность
    user_data.setdefault('activity', []).append({
        'type': 'bookmark',
        'text': f'добавил(а) фильм "{movie_title}" в категорию "{category}"',
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'icon': 'fas fa-bookmark',
        'movie': movie_title,
        'poster': movie_poster,
        'movie_id': int(movie_id) # Добавлено для ссылки в активности
    })
    
    save_data('data/users.json', users)
    check_achievements(username) # Проверяем достижения после добавления закладки
    flash(f"Фильм '{movie_title}' добавлен в закладки ({category}).", "success")
    return redirect(url_for('movie_detail', tmdb_id=movie_id))


@app.route('/remove_bookmark', methods=['POST'])
def remove_bookmark():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.get_json(force=True)
    movie_id = data.get('movie_id')
    category = data.get('category')
    
    if not movie_id or not category:
        return jsonify({'success': False, 'message': 'Bad request: movie_id or category missing'}), 400

    username = session['username']
    user_data = users.get(username)
    if not user_data:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    bookmarks = user_data.get('bookmarks', {})

    reverse_mapping = {
        'watching': 'Смотрю',
        'plan': 'Буду смотреть', # Исправлено
        'dropped': 'Брошено',
        'watched': 'Просмотрено',
        'favorites': 'Любимые'
        }
    rus_cat = reverse_mapping.get(category, category)

    if rus_cat in bookmarks:
        initial_len = len(bookmarks[rus_cat])
        bookmarks[rus_cat] = [m for m in bookmarks[rus_cat] if str(m.get('id')) != str(movie_id)]
        
        if len(bookmarks[rus_cat]) < initial_len:
            save_data('data/users.json', users)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Movie not found in specified category'}), 404
    else:
        return jsonify({'success': False, 'message': 'Category not found'}), 404




@app.route('/threads')
def threads_page():
    # Логика для получения и фильтрации тредов
    # Например, можно добавить параметры запроса для фильтрации по тегам и сортировки
    all_threads = list(threads.values()) # Получаем все треды
    
    # Пример простой сортировки по дате создания (новые сверху)
    all_threads.sort(key=lambda x: datetime.strptime(x['created_at'], "%Y-%m-%d %H:%M:%S"), reverse=True)
    # Здесь можно добавить логику для тегов и пагинации
    
    return render_template('threads.html', threads=all_threads)

@app.route('/thread/<thread_id>')
def thread_detail(thread_id):
    thread = threads.get(thread_id)
    if not thread:
        flash("Тред не найден.", "error")
        return redirect(url_for('threads_page'))
    # Получаем данные фильма, если тред связан с TMDB ID
    movie_data = None
    if thread.get('tmdb_id'):
        actors, genres, title, poster_path, overview, release_date, vote_average = get_movie_data(thread['tmdb_id'])
        movie_data = {
            'id': thread['tmdb_id'],
            'title': title,
            'poster_path': poster_path,
            'genres': genres,
            'overview': overview,
            'release_date': release_date,
            'vote_average': vote_average
        }

    return render_template('thread_detail.html', 
                           thread=thread, 
                           movie_data=movie_data)


@app.route('/api/threads', methods=['POST'])
def create_thread():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = session['username']
    data = request.json
    
    title = data.get('title')
    tmdb_id = data.get('tmdb_id')
    tags = data.get('tags', [])
    initial_post = data.get('initial_post', '')
    if not title or not tmdb_id:
        return jsonify({'error': 'Title and TMDB ID are required'}), 400
    new_thread_id = str(uuid.uuid4())
    new_thread = {
        'id': new_thread_id,
        'title': title,
        'tmdb_id': int(tmdb_id),
        'tags': tags,
        'created_by': username,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'initial_post': initial_post,
        'comments': []
    }
    
    threads[new_thread_id] = new_thread
    save_data('data/threads.json', threads)
    user_data = users.get(username)
    if user_data:
        user_data.setdefault('activity', []).append({
            'type': 'thread_created',
            'text': f'создал(а) новый тред "{title}"',
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'icon': 'fas fa-comments',
            'thread_id': new_thread_id,
            'thread_title': title
        })
        save_data('data/users.json', users)
    
    return jsonify({'success': True, 'thread_id': new_thread_id})


@app.route('/api/thread/<thread_id>/comment', methods=['POST'])
def add_thread_comment(thread_id):
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = session['username']
    data = request.json
    comment_text = data.get('text')
    if not comment_text:
        return jsonify({'error': 'Comment text is required'}), 400
    thread = threads.get(thread_id)
    if not thread:
        return jsonify({'error': 'Thread not found'}), 404
    new_comment = {
        'comment_id': str(uuid.uuid4()),
        'user': username,
        'text': comment_text,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    thread.setdefault('comments', []).append(new_comment)
    save_data('data/threads.json', threads)
    user_data = users.get(username)
    if user_data:
        user_data.setdefault('activity', []).append({
            'type': 'thread_comment',
            'text': f'прокомментировал(а) тред "{thread.get("title", "Неизвестный тред")}"',
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'icon': 'fas fa-comment-dots',
            'thread_id': thread_id,
            'thread_title': thread.get('title', 'Неизвестный тред'),
            'comment': comment_text
        })
        save_data('data/users.json', users)
    return jsonify({'success': True, 'comment': new_comment})


@app.route('/api/user/<target_username>/follow', methods=['POST'])
def follow_user(target_username):
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_username = session['username']
    if current_username == target_username:
        return jsonify({'error': 'Cannot follow yourself'}), 400
    current_user_data = users.get(current_username)
    target_user_data = users.get(target_username)
    if not current_user_data or not target_user_data:
        return jsonify({'error': 'User not found'}), 404
    current_user_data.setdefault('following', [])
    
    action = ''
    if target_username in current_user_data['following']:
        current_user_data['following'].remove(target_username)
        action = 'unfollowed'
    else:
        current_user_data['following'].append(target_username)
        action = 'followed'
    
    save_data('data/users.json', users)
    return jsonify({'success': True, 'action': action})



if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    app.run(debug=True)

