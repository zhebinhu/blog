# -*- coding:utf-8 -*-
from flask import abort, flash, current_app, render_template, request, url_for, redirect, make_response, g, jsonify
from flask_login import current_user, login_required

from .. import db
from ..decorators import admin_required, permission_required
from ..main import main
from ..main.forms import EditProfileForm, EditProfileAdminForm, PostForm, CommentForm
from ..models import User, Role, Permission, Post, Comment, Follow


@main.route('/', methods=['GET', 'POST'])
def index():
    postform = PostForm()
    loginform = g.loginform
    registrationform = g.registrationform
    if loginform.validate_on_submit():
        user = User.query.filter_by(email=loginform.email.data).first()
        if user is not None and user.verify_password(loginform.password.data):
            from flask_login import login_user
            login_user(user, loginform.remember_me.data)
            return redirect(request.args.get('next') or url_for('main.index'))
    else:
        redirect(request.args.get('next') or url_for('main.index'))
    from app import db
    from app.email import send_email
    if registrationform.validate_on_submit():
        user = User(email=registrationform.email.data, username=registrationform.username.data,
                    password=registrationform.password.data)
        db.session.add(user)
        db.session.commit()
        token = user.generate_confirmation_token()
        send_email(user.email, u'认证您的邮箱', 'auth/email/confirm', user=user, token=token)
        flash(u'注册成功！一封认证邮件已发送到您的邮箱')
        return redirect(url_for('auth.login'))
    if current_user.can(Permission.WRITE_ARTICLES) and postform.validate_on_submit():
        post = Post(body=postform.body.data, author=current_user._get_current_object())
        db.session.add(post)
        return redirect(url_for('main.index'))
    page = request.args.get('page', 1, type=int)
    show_followed = False
    if current_user.is_authenticated:
        show_followed = bool(request.cookies.get('show_followed',''))
    if show_followed:
        query = current_user.followed_posts
    else:
        query = Post.query
    pagination = query.order_by(Post.timestamp.desc()).paginate(page,per_page=current_app.config['BLOG_POSTS_PER_PAGE'],error_out=False)
    posts = pagination.items
    if current_user.is_authenticated:
        followeds = User.query.filter(User.id.in_([item.followed.id for item in current_user.followed if item.followed.id!=current_user.id])).order_by(User.last_seen.desc()).limit(10).all()
        return render_template('index.html', postform=postform, posts=posts, pagination=pagination,show_followed=show_followed,followeds = followeds)
    return render_template('index.html', postform=postform, posts=posts, pagination=pagination, show_followed=show_followed)

@main.route('/user/<username>', methods=['GET', 'POST'])
def user(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        abort(404)
    page = request.args.get('page', 1, type=int)
    pagination = user.posts.order_by(Post.timestamp.desc()).paginate(
        page, per_page=current_app.config['BLOG_POSTS_PER_PAGE'], error_out=False
    )
    posts = pagination.items
    return render_template('user.html', user=user, posts=posts, pagination=pagination)


@main.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.location = form.location.data
        current_user.about_me = form.about_me.data
        db.session.add(current_user)
        flash(u'您的资料已更新')
        return redirect(url_for('main.user', username=current_user.username))
    form.name.data = current_user.name
    form.location.data = current_user.location
    form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', form=form)


@main.route('/edit-profile/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_profile_admin(id):
    user = User.query.get_or_404(id)
    form = EditProfileAdminForm(user=user)
    if form.validate_on_submit():
        user.email = form.email.data
        user.username = form.username.data
        user.confirmed = form.confirmed.data
        user.role = Role.query.get(form.role.data)
        user.name = form.name.data
        user.location = form.location.data
        user.about_me = form.about_me.data
        db.session.add(user)
        flash(u'用户资料已更新')
        return redirect(url_for('.user', username=user.username))
    form.email.data = user.email
    form.username.data = user.username
    form.confirmed.data = user.confirmed
    form.role.data = user.role_id
    form.name.data = user.name
    form.location.data = user.location
    form.about_me.data = user.about_me
    return render_template('edit_profile.html', form=form, user=user)


@main.route('/post/<int:id>', methods=['GET', 'POST'])
def post(id):
    post = Post.query.get_or_404(id)
    commentform = CommentForm()
    if commentform.validate_on_submit():
        comment = Comment(body=commentform.body.data,post=post,author=current_user._get_current_object())
        db.session.add(comment)
        flash(u'你的评论已提交')
        return redirect(url_for('.post',id=post.id,page=-1))
    page = request.args.get('page',1,type=int)
    if page == -1:
        page = (post.comments.count() - 1) / current_app.config['BLOG_COMMENTS_PER_PAGE'] + 1
    pagination = post.comments.order_by(Comment.timestamp.asc()).paginate(page, per_page=current_app.config['BLOG_COMMENTS_PER_PAGE'], error_out=False)
    comments = pagination.items
    return render_template('post.html', posts=[post], commentform=commentform,comments=comments)


@main.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    post = Post.query.get_or_404(id)
    if current_user != post.author and not current_user.can(Permission.ADMINISTER):
        abort(403)
    form = PostForm()
    if form.validate_on_submit():
        post.body = form.body.data
        db.session.add(post)
        flash(u'博客已更新')
        return redirect(url_for('.post', id=post.id))
    form.body.data = post.body
    return render_template('edit_post.html', form=form)


@main.route('/follow/<username>')
@login_required
@permission_required(Permission.FOLLOW)
def follow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash(u'不存在的用户')
        return redirect(url_for('.index'))
    if current_user.is_following(user):
        flash(u'你已经关注了TA')
        return redirect(url_for('.user', username=username))
    current_user.follow(user)
    flash(u'现在你关注了{username}'.format(username=username))
    return redirect(url_for('.user', username=username))


@main.route('/unfollow/<username>')
@login_required
@permission_required(Permission.FOLLOW)
def unfollow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash(u'不存在的用户')
        return redirect(url_for('.index'))
    if not current_user.is_following(user):
        flash(u'该用户不在你的关注列表中')
        return redirect(url_for('.user',username=username))
    current_user.unfollow(user)
    flash(u'你不再关注{username}'.format(username=username))
    return redirect(url_for('.user',username=username))


@main.route('/followers/<username>', methods=['GET', 'POST'])
def followers(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash(u'不存在的用户')
        return redirect(url_for('.index'))
    page = request.args.get('page', 1, type=int)
    pagination = user.followers.paginate(
        page, per_page=current_app.config['BLOG_FOLLOWERS_PER_PAGE'],
        error_out=False)
    follows = [{'user': item.follower, 'timestamp': item.timestamp}
               for item in pagination.items]
    return render_template('followers.html', user=user, title=u"的粉丝",
                           endpoint='.followers', pagination=pagination,
                           follows=follows)


@main.route('/followed-by/<username>',methods=['GET', 'POST'])
def followed_by(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash(u'不存在的用户')
        return redirect(url_for('.index'))
    page = request.args.get('page', 1, type=int)
    pagination = user.followed.paginate(
        page, per_page=current_app.config['BLOG_FOLLOWERS_PER_PAGE'],
        error_out=False)
    follows = [{'user': item.followed, 'timestamp': item.timestamp}
               for item in pagination.items]
    return render_template('followers.html', user=user, title=u"的关注",
                           endpoint='.followed_by', pagination=pagination,
                           follows=follows)

@main.route('/all')
@login_required
def show_all():
    resp = make_response(redirect(url_for('.index')))
    resp.set_cookie('show_followed','',max_age=30*24*60*60)
    return resp

@main.route('/followed')
@login_required
def show_followed():
    resp = make_response(redirect(url_for('.index')))
    resp.set_cookie('show_followed','1',max_age=30*24*60*60)
    return resp

@main.route('/moderate')
@login_required
@permission_required(Permission.MODERATE_COMMENTS)
def moderate():
    page = request.args.get('page', 1, type=int)
    pagination = Comment.query.order_by(Comment.timestamp.desc()).paginate(page, per_page=current_app.config['BLOG_COMMENTS_PER_PAGE'],error_out=False)
    comments = pagination.items
    return render_template('moderate.html', comments=comments,pagination=pagination, page=page)

@main.route('/moderate/enable/<int:id>')
@login_required
@permission_required(Permission.MODERATE_COMMENTS)
def moderate_enable(id):
    comment = Comment.query.get_or_404(id)
    comment.disabled = False
    db.session.add(comment)
    return redirect(url_for('.moderate',page=request.args.get('page', 1, type=int)))


@main.route('/moderate/disable/<int:id>')
@login_required
@permission_required(Permission.MODERATE_COMMENTS)
def moderate_disable(id):
    comment = Comment.query.get_or_404(id)
    comment.disabled = True
    db.session.add(comment)
    return redirect(url_for('.moderate',page=request.args.get('page', 1, type=int)))

@main.route('/like')
@login_required
def like():
    id = request.args.get('id', 0, type=int)
    post = Post.query.filter_by(id=id).first()
    if post is None:
        flash(u'不存在的微博')
        return jsonify(result=False)
    if current_user.is_liking(post):
        flash(u'你已经赞了这篇微博')
        return jsonify(result=False)
    current_user.posts_liked.append(post)
    counts = post.users_liked.count()
    return jsonify(result=True,counts=counts)


@main.route('/unlike')
@login_required
def unlike():
    id = request.args.get('id', 0, type=int)
    post = Post.query.filter_by(id=id).first()
    if post is None:
        flash(u'不存在的微博')
        return jsonify(result=False)
    if not current_user.is_liking(post):
        flash(u'你还没有赞这篇微博')
        return jsonify(result=False)
    current_user.posts_liked.remove(post)
    counts = post.users_liked.count()
    return jsonify(result=True,counts=counts)
