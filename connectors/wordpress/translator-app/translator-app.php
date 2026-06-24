<?php
/**
 * Plugin Name: Translator App
 * Description: Sends WordPress content to the Translator App API and can create translated posts for review/publishing.
 * Version: 0.2.0
 */

if (!defined('ABSPATH')) {
    exit;
}

const TRANSLATOR_APP_TRANSLATED_META_KEY = '_translator_app_translations';
const TRANSLATOR_APP_TRANSLATION_POST_IDS_META_KEY = '_translator_app_translation_post_ids';
const TRANSLATOR_APP_SOURCE_POST_ID_META_KEY = '_translator_app_source_post_id';
const TRANSLATOR_APP_SOURCE_LANGUAGE_META_KEY = '_translator_app_source_language';
const TRANSLATOR_APP_TARGET_LANGUAGE_META_KEY = '_translator_app_target_language';
const TRANSLATOR_APP_LANGUAGE_PLUGIN_META_KEY = '_translator_app_language_plugin';

add_action('admin_menu', function () {
    add_options_page(
        'Translator App',
        'Translator App',
        'manage_options',
        'translator-app',
        'translator_app_settings_page'
    );
});

add_action('admin_init', function () {
    register_setting('translator_app', 'translator_app_api_base_url', [
        'sanitize_callback' => 'esc_url_raw',
    ]);
    register_setting('translator_app', 'translator_app_api_key', [
        'sanitize_callback' => 'sanitize_text_field',
    ]);
    register_setting('translator_app', 'translator_app_default_source_language', [
        'sanitize_callback' => 'translator_app_sanitize_language_code',
    ]);
    register_setting('translator_app', 'translator_app_default_target_language', [
        'sanitize_callback' => 'translator_app_sanitize_language_code',
    ]);
    register_setting('translator_app', 'translator_app_translation_provider', [
        'sanitize_callback' => 'translator_app_sanitize_provider',
    ]);
    register_setting('translator_app', 'translator_app_translation_model', [
        'sanitize_callback' => 'sanitize_text_field',
    ]);
    register_setting('translator_app', 'translator_app_publish_mode', [
        'sanitize_callback' => 'translator_app_sanitize_publish_mode',
    ]);
    register_setting('translator_app', 'translator_app_translated_post_status', [
        'sanitize_callback' => 'translator_app_sanitize_post_status',
    ]);
    register_setting('translator_app', 'translator_app_language_integration', [
        'sanitize_callback' => 'translator_app_sanitize_language_integration',
    ]);
    register_setting('translator_app', 'translator_app_translate_title', [
        'sanitize_callback' => 'translator_app_sanitize_checkbox',
    ]);
    register_setting('translator_app', 'translator_app_translate_excerpt', [
        'sanitize_callback' => 'translator_app_sanitize_checkbox',
    ]);
    register_setting('translator_app', 'translator_app_copy_featured_image', [
        'sanitize_callback' => 'translator_app_sanitize_checkbox',
    ]);
});

add_action('admin_init', function () {
    foreach (translator_app_supported_post_types() as $post_type) {
        add_filter('bulk_actions-edit-' . $post_type, 'translator_app_register_bulk_action');
        add_filter('handle_bulk_actions-edit-' . $post_type, 'translator_app_handle_bulk_action', 10, 3);
    }
});

add_action('admin_notices', function () {
    if (!empty($_GET['translator_app_translated'])) {
        $target = sanitize_text_field(wp_unslash($_GET['translator_app_target'] ?? ''));
        $translated_post_id = intval($_GET['translator_app_post_id'] ?? 0);
        $link = $translated_post_id ? get_edit_post_link($translated_post_id) : '';
        echo '<div class="notice notice-success is-dismissible"><p>';
        echo esc_html(sprintf('Translator App completed translation to %s.', strtoupper($target)));
        if ($link) {
            echo ' <a href="' . esc_url($link) . '">' . esc_html__('Open translated post', 'translator-app') . '</a>';
        }
        echo '</p></div>';
    }

    if (!empty($_GET['translator_app_bulk_translated'])) {
        $count = intval($_GET['translator_app_bulk_translated']);
        $failed = intval($_GET['translator_app_bulk_failed'] ?? 0);
        echo '<div class="notice notice-success is-dismissible"><p>';
        echo esc_html(sprintf('Translator App translated %d item(s).', $count));
        if ($failed > 0) {
            echo ' ' . esc_html(sprintf('%d item(s) failed; check configuration and API logs.', $failed));
        }
        echo '</p></div>';
    }
});

add_action('add_meta_boxes', function ($post_type, $post) {
    if (!translator_app_is_supported_post_type($post_type)) {
        return;
    }

    add_meta_box(
        'translator_app_translations',
        'Translator App',
        'translator_app_post_meta_box',
        $post_type,
        'side',
        'default'
    );
}, 10, 2);

add_action('post_submitbox_misc_actions', function () {
    global $post;
    if (!$post || !translator_app_is_supported_post_type($post->post_type)) {
        return;
    }

    $url = wp_nonce_url(
        admin_url('admin-post.php?action=translator_app_translate_post&post_id=' . $post->ID),
        'translator_app_translate_post_' . $post->ID
    );
    echo '<div class="misc-pub-section"><a class="button" href="' . esc_url($url) . '">' . esc_html__('Translate with Translator App', 'translator-app') . '</a></div>';
});

add_action('admin_post_translator_app_translate_post', function () {
    $post_id = intval($_GET['post_id'] ?? 0);
    if (!$post_id || !current_user_can('edit_post', $post_id)) {
        wp_die('Insufficient permissions.');
    }

    check_admin_referer('translator_app_translate_post_' . $post_id);

    $post = get_post($post_id);
    if (!$post || !translator_app_is_supported_post_type($post->post_type)) {
        wp_die('Post type is not supported.');
    }

    $response = translator_app_translate_wordpress_post($post);
    if (is_wp_error($response)) {
        wp_die(esc_html($response->get_error_message()));
    }

    $redirect = get_edit_post_link($post_id, 'raw');
    $redirect = add_query_arg([
        'translator_app_translated' => 1,
        'translator_app_target' => $response['target_language'] ?? '',
        'translator_app_post_id' => intval($response['translated_post_id'] ?? 0),
    ], $redirect);

    wp_safe_redirect($redirect);
    exit;
});

function translator_app_settings_page() {
    $publish_mode = get_option('translator_app_publish_mode', 'create_post');
    $post_status = get_option('translator_app_translated_post_status', 'draft');
    $language_integration = get_option('translator_app_language_integration', 'auto');
    $provider = get_option('translator_app_translation_provider', '');
    ?>
    <div class="wrap">
        <h1>Translator App</h1>
        <form method="post" action="options.php">
            <?php settings_fields('translator_app'); ?>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="translator_app_api_base_url">API Base URL</label></th>
                    <td><input class="regular-text" id="translator_app_api_base_url" name="translator_app_api_base_url" value="<?php echo esc_attr(get_option('translator_app_api_base_url', 'http://127.0.0.1:8000')); ?>"></td>
                </tr>
                <tr>
                    <th scope="row"><label for="translator_app_api_key">API Key</label></th>
                    <td><input class="regular-text" id="translator_app_api_key" name="translator_app_api_key" type="password" value="<?php echo esc_attr(get_option('translator_app_api_key', '')); ?>"></td>
                </tr>
                <tr>
                    <th scope="row"><label for="translator_app_default_source_language">Source Language</label></th>
                    <td><input id="translator_app_default_source_language" name="translator_app_default_source_language" value="<?php echo esc_attr(get_option('translator_app_default_source_language', 'en')); ?>"></td>
                </tr>
                <tr>
                    <th scope="row"><label for="translator_app_default_target_language">Target Language</label></th>
                    <td><input id="translator_app_default_target_language" name="translator_app_default_target_language" value="<?php echo esc_attr(get_option('translator_app_default_target_language', 'es')); ?>"></td>
                </tr>
                <tr>
                    <th scope="row"><label for="translator_app_translation_provider">Translation Provider</label></th>
                    <td>
                        <select id="translator_app_translation_provider" name="translator_app_translation_provider">
                            <option value="" <?php selected($provider, ''); ?>>Server default</option>
                            <option value="nllb" <?php selected($provider, 'nllb'); ?>>NLLB</option>
                            <option value="openai" <?php selected($provider, 'openai'); ?>>OpenAI</option>
                            <option value="gemini" <?php selected($provider, 'gemini'); ?>>Gemini</option>
                            <option value="libretranslate" <?php selected($provider, 'libretranslate'); ?>>LibreTranslate</option>
                            <option value="demo" <?php selected($provider, 'demo'); ?>>Demo</option>
                        </select>
                        <p class="description">Provider keys stay on the Translator App server. WordPress only stores the Translator App API key.</p>
                    </td>
                </tr>
                <tr>
                    <th scope="row"><label for="translator_app_translation_model">Model Override</label></th>
                    <td><input class="regular-text" id="translator_app_translation_model" name="translator_app_translation_model" value="<?php echo esc_attr(get_option('translator_app_translation_model', '')); ?>" placeholder="Use provider default"></td>
                </tr>
                <tr>
                    <th scope="row"><label for="translator_app_publish_mode">Output Mode</label></th>
                    <td>
                        <select id="translator_app_publish_mode" name="translator_app_publish_mode">
                            <option value="create_post" <?php selected($publish_mode, 'create_post'); ?>>Create or update translated post</option>
                            <option value="meta_only" <?php selected($publish_mode, 'meta_only'); ?>>Store translated HTML in post meta only</option>
                        </select>
                    </td>
                </tr>
                <tr>
                    <th scope="row"><label for="translator_app_translated_post_status">Translated Post Status</label></th>
                    <td>
                        <select id="translator_app_translated_post_status" name="translator_app_translated_post_status">
                            <option value="draft" <?php selected($post_status, 'draft'); ?>>Draft</option>
                            <option value="pending" <?php selected($post_status, 'pending'); ?>>Pending review</option>
                            <option value="private" <?php selected($post_status, 'private'); ?>>Private</option>
                            <option value="publish" <?php selected($post_status, 'publish'); ?>>Publish</option>
                            <option value="same_status" <?php selected($post_status, 'same_status'); ?>>Same as source post</option>
                        </select>
                    </td>
                </tr>
                <tr>
                    <th scope="row"><label for="translator_app_language_integration">Language Plugin</label></th>
                    <td>
                        <select id="translator_app_language_integration" name="translator_app_language_integration">
                            <option value="auto" <?php selected($language_integration, 'auto'); ?>>Auto-detect WPML or Polylang</option>
                            <option value="polylang" <?php selected($language_integration, 'polylang'); ?>>Polylang</option>
                            <option value="wpml" <?php selected($language_integration, 'wpml'); ?>>WPML</option>
                            <option value="none" <?php selected($language_integration, 'none'); ?>>No language plugin</option>
                        </select>
                    </td>
                </tr>
                <tr>
                    <th scope="row">Translation Options</th>
                    <td>
                        <input type="hidden" name="translator_app_translate_title" value="0">
                        <label><input type="checkbox" name="translator_app_translate_title" value="1" <?php checked(get_option('translator_app_translate_title', '1'), '1'); ?>> Translate title</label><br>
                        <input type="hidden" name="translator_app_translate_excerpt" value="0">
                        <label><input type="checkbox" name="translator_app_translate_excerpt" value="1" <?php checked(get_option('translator_app_translate_excerpt', '1'), '1'); ?>> Translate excerpt</label><br>
                        <input type="hidden" name="translator_app_copy_featured_image" value="0">
                        <label><input type="checkbox" name="translator_app_copy_featured_image" value="1" <?php checked(get_option('translator_app_copy_featured_image', '1'), '1'); ?>> Copy featured image</label>
                    </td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>
    </div>
    <?php
}

function translator_app_post_meta_box(WP_Post $post) {
    $url = wp_nonce_url(
        admin_url('admin-post.php?action=translator_app_translate_post&post_id=' . $post->ID),
        'translator_app_translate_post_' . $post->ID
    );
    echo '<p><a class="button button-primary" href="' . esc_url($url) . '">' . esc_html__('Translate with Translator App', 'translator-app') . '</a></p>';

    $translation_post_ids = get_post_meta($post->ID, TRANSLATOR_APP_TRANSLATION_POST_IDS_META_KEY, true);
    if (!is_array($translation_post_ids) || empty($translation_post_ids)) {
        echo '<p>' . esc_html__('No translated posts have been created yet.', 'translator-app') . '</p>';
        return;
    }

    echo '<ul>';
    foreach ($translation_post_ids as $language => $translated_post_id) {
        $translated_post = get_post((int) $translated_post_id);
        if (!$translated_post) {
            continue;
        }
        $link = get_edit_post_link($translated_post->ID);
        echo '<li>' . esc_html(strtoupper($language)) . ': <a href="' . esc_url($link) . '">' . esc_html(get_the_title($translated_post)) . '</a></li>';
    }
    echo '</ul>';
}

function translator_app_register_bulk_action(array $actions): array {
    $actions['translator_app_translate'] = 'Translate with Translator App';
    return $actions;
}

function translator_app_handle_bulk_action(string $redirect_to, string $action, array $post_ids): string {
    if ($action !== 'translator_app_translate') {
        return $redirect_to;
    }

    $translated = 0;
    $failed = 0;
    foreach ($post_ids as $post_id) {
        if (!current_user_can('edit_post', $post_id)) {
            $failed++;
            continue;
        }
        $post = get_post((int) $post_id);
        if (!$post || !translator_app_is_supported_post_type($post->post_type)) {
            $failed++;
            continue;
        }
        $result = translator_app_translate_wordpress_post($post);
        if (is_wp_error($result)) {
            $failed++;
            continue;
        }
        $translated++;
    }

    return add_query_arg([
        'translator_app_bulk_translated' => $translated,
        'translator_app_bulk_failed' => $failed,
    ], $redirect_to);
}

function translator_app_translate_wordpress_post(WP_Post $post) {
    $source_language = get_option('translator_app_default_source_language', 'en');
    $target_language = get_option('translator_app_default_target_language', 'es');
    $metadata = [
        'wordpress_post_id' => $post->ID,
        'wordpress_post_status' => $post->post_status,
        'wordpress_post_type' => $post->post_type,
    ];

    $content_payload = translator_app_translate_text_via_api(
        $post->post_content,
        'wp-post-' . $post->ID . '-content',
        $post->post_type,
        get_the_title($post),
        $source_language,
        $target_language,
        'html',
        $metadata
    );
    if (is_wp_error($content_payload)) {
        return $content_payload;
    }

    $translated_title = get_the_title($post);
    if (get_option('translator_app_translate_title', '1') === '1' && $translated_title !== '') {
        $title_payload = translator_app_translate_text_via_api(
            $translated_title,
            'wp-post-' . $post->ID . '-title',
            $post->post_type . '-title',
            $translated_title,
            $source_language,
            $target_language,
            'text',
            $metadata
        );
        if (is_wp_error($title_payload)) {
            return $title_payload;
        }
        $translated_title = $title_payload['translated_text'] ?? $translated_title;
    }

    $translated_excerpt = $post->post_excerpt;
    if (get_option('translator_app_translate_excerpt', '1') === '1' && trim($post->post_excerpt) !== '') {
        $excerpt_payload = translator_app_translate_text_via_api(
            $post->post_excerpt,
            'wp-post-' . $post->ID . '-excerpt',
            $post->post_type . '-excerpt',
            get_the_title($post),
            $source_language,
            $target_language,
            'html',
            $metadata
        );
        if (is_wp_error($excerpt_payload)) {
            return $excerpt_payload;
        }
        $translated_excerpt = $excerpt_payload['translated_text'] ?? $translated_excerpt;
    }

    $translated_content = $content_payload['translated_text'] ?? '';
    translator_app_store_translation_meta(
        $post->ID,
        $target_language,
        $translated_content,
        $translated_title,
        $translated_excerpt,
        $content_payload
    );

    $translated_post_id = 0;
    $publish_mode = get_option('translator_app_publish_mode', 'create_post');
    if ($publish_mode === 'create_post') {
        $translated_post_id = translator_app_upsert_translated_post(
            $post,
            $translated_content,
            $translated_title,
            $translated_excerpt,
            $source_language,
            $target_language
        );
        if (is_wp_error($translated_post_id)) {
            return $translated_post_id;
        }
    }

    return [
        'translated_text' => $translated_content,
        'translated_title' => $translated_title,
        'translated_excerpt' => $translated_excerpt,
        'translated_post_id' => $translated_post_id,
        'source_language' => $source_language,
        'target_language' => $target_language,
        'provider' => $content_payload['provider'] ?? '',
        'translation_model' => $content_payload['translation_model'] ?? '',
    ];
}

function translator_app_translate_text_via_api(
    string $text,
    string $external_content_id,
    string $content_type,
    string $title,
    string $source_language,
    string $target_language,
    string $format,
    array $metadata
) {
    $body = [
        'external_content_id' => $external_content_id,
        'content_type' => $content_type,
        'title' => $title,
        'source_language' => $source_language,
        'target_language' => $target_language,
        'format' => $format,
        'text' => $text,
        'metadata' => $metadata,
    ];

    $provider = trim((string) get_option('translator_app_translation_provider', ''));
    $model = trim((string) get_option('translator_app_translation_model', ''));
    if ($provider !== '') {
        $body['provider'] = $provider;
    }
    if ($model !== '') {
        $body['model'] = $model;
    }

    $endpoint = $format === 'html' ? '/api/v1/translate/html' : '/api/v1/translate';
    $payload = translator_app_api_request($endpoint, $body);
    if (is_wp_error($payload)) {
        return $payload;
    }
    if (empty($payload['translated_text'])) {
        return new WP_Error('translator_app_empty_translation', 'Translator App API did not return translated_text.');
    }

    return $payload;
}

function translator_app_api_request(string $endpoint, array $body) {
    $base_url = rtrim((string) get_option('translator_app_api_base_url', ''), '/');
    $api_key = (string) get_option('translator_app_api_key', '');
    if (!$base_url || !$api_key) {
        return new WP_Error('translator_app_missing_config', 'Translator App API URL and key are required.');
    }

    $response = wp_remote_post($base_url . $endpoint, [
        'headers' => [
            'Content-Type' => 'application/json',
            'X-API-Key' => $api_key,
        ],
        'body' => wp_json_encode($body),
        'timeout' => 90,
    ]);

    if (is_wp_error($response)) {
        return $response;
    }

    $status = wp_remote_retrieve_response_code($response);
    $payload = json_decode(wp_remote_retrieve_body($response), true);
    if (!is_array($payload)) {
        return new WP_Error('translator_app_invalid_json', 'Translator App API returned invalid JSON.');
    }
    if ($status >= 400) {
        return new WP_Error('translator_app_api_error', $payload['detail'] ?? 'Translator App API request failed.');
    }

    return $payload;
}

function translator_app_store_translation_meta(
    int $source_post_id,
    string $target_language,
    string $translated_content,
    string $translated_title,
    string $translated_excerpt,
    array $payload
): void {
    $translations = get_post_meta($source_post_id, TRANSLATOR_APP_TRANSLATED_META_KEY, true);
    if (!is_array($translations)) {
        $translations = [];
    }

    $translations[$target_language] = [
        'content' => $translated_content,
        'title' => $translated_title,
        'excerpt' => $translated_excerpt,
        'provider' => $payload['provider'] ?? '',
        'translation_model' => $payload['translation_model'] ?? '',
        'updated_at' => current_time('mysql'),
    ];
    update_post_meta($source_post_id, TRANSLATOR_APP_TRANSLATED_META_KEY, $translations);
}

function translator_app_upsert_translated_post(
    WP_Post $source_post,
    string $translated_content,
    string $translated_title,
    string $translated_excerpt,
    string $source_language,
    string $target_language
) {
    $translated_post_id = translator_app_find_translated_post_id($source_post->ID, $target_language);
    $post_status = translator_app_resolve_translated_post_status($source_post);
    $post_data = [
        'post_type' => $source_post->post_type,
        'post_status' => $post_status,
        'post_author' => $source_post->post_author,
        'post_title' => $translated_title ?: $source_post->post_title,
        'post_content' => $translated_content,
        'post_excerpt' => $translated_excerpt,
        'post_parent' => $source_post->post_parent,
        'menu_order' => $source_post->menu_order,
        'comment_status' => $source_post->comment_status,
        'ping_status' => $source_post->ping_status,
    ];

    if ($translated_post_id) {
        $post_data['ID'] = $translated_post_id;
        $result = wp_update_post($post_data, true);
    } else {
        $slug_base = $source_post->post_name ?: sanitize_title($source_post->post_title);
        $post_data['post_name'] = wp_unique_post_slug(
            sanitize_title($slug_base . '-' . $target_language),
            0,
            $post_status,
            $source_post->post_type,
            $source_post->post_parent
        );
        $result = wp_insert_post($post_data, true);
    }

    if (is_wp_error($result)) {
        return $result;
    }

    $translated_post_id = (int) $result;
    update_post_meta($translated_post_id, TRANSLATOR_APP_SOURCE_POST_ID_META_KEY, $source_post->ID);
    update_post_meta($translated_post_id, TRANSLATOR_APP_SOURCE_LANGUAGE_META_KEY, $source_language);
    update_post_meta($translated_post_id, TRANSLATOR_APP_TARGET_LANGUAGE_META_KEY, $target_language);

    translator_app_copy_post_context($source_post, $translated_post_id);
    $language_plugin = translator_app_assign_language($source_post->ID, $translated_post_id, $source_language, $target_language, $source_post->post_type);
    update_post_meta($translated_post_id, TRANSLATOR_APP_LANGUAGE_PLUGIN_META_KEY, $language_plugin);

    $translation_post_ids = get_post_meta($source_post->ID, TRANSLATOR_APP_TRANSLATION_POST_IDS_META_KEY, true);
    if (!is_array($translation_post_ids)) {
        $translation_post_ids = [];
    }
    $translation_post_ids[$target_language] = $translated_post_id;
    update_post_meta($source_post->ID, TRANSLATOR_APP_TRANSLATION_POST_IDS_META_KEY, $translation_post_ids);

    return $translated_post_id;
}

function translator_app_find_translated_post_id(int $source_post_id, string $target_language): int {
    $translation_post_ids = get_post_meta($source_post_id, TRANSLATOR_APP_TRANSLATION_POST_IDS_META_KEY, true);
    if (is_array($translation_post_ids) && !empty($translation_post_ids[$target_language])) {
        $post = get_post((int) $translation_post_ids[$target_language]);
        if ($post) {
            return (int) $translation_post_ids[$target_language];
        }
    }

    $posts = get_posts([
        'post_type' => 'any',
        'post_status' => 'any',
        'posts_per_page' => 1,
        'fields' => 'ids',
        'meta_query' => [
            'relation' => 'AND',
            [
                'key' => TRANSLATOR_APP_SOURCE_POST_ID_META_KEY,
                'value' => $source_post_id,
            ],
            [
                'key' => TRANSLATOR_APP_TARGET_LANGUAGE_META_KEY,
                'value' => $target_language,
            ],
        ],
    ]);

    return empty($posts) ? 0 : (int) $posts[0];
}

function translator_app_copy_post_context(WP_Post $source_post, int $translated_post_id): void {
    if (get_option('translator_app_copy_featured_image', '1') === '1') {
        $thumbnail_id = get_post_thumbnail_id($source_post->ID);
        if ($thumbnail_id) {
            set_post_thumbnail($translated_post_id, $thumbnail_id);
        }
    }

    $template = get_page_template_slug($source_post->ID);
    if ($template) {
        update_post_meta($translated_post_id, '_wp_page_template', $template);
    }

    foreach (get_object_taxonomies($source_post->post_type, 'objects') as $taxonomy => $taxonomy_object) {
        if (in_array($taxonomy, ['language', 'post_translations'], true)) {
            continue;
        }
        if (empty($taxonomy_object->show_ui) && empty($taxonomy_object->public)) {
            continue;
        }
        $terms = wp_get_object_terms($source_post->ID, $taxonomy, ['fields' => 'ids']);
        if (!is_wp_error($terms)) {
            wp_set_object_terms($translated_post_id, array_map('intval', $terms), $taxonomy, false);
        }
    }
}

function translator_app_assign_language(
    int $source_post_id,
    int $translated_post_id,
    string $source_language,
    string $target_language,
    string $post_type
): string {
    $mode = get_option('translator_app_language_integration', 'auto');

    if (($mode === 'auto' || $mode === 'polylang') && function_exists('pll_set_post_language')) {
        $detected_source_language = function_exists('pll_get_post_language') ? pll_get_post_language($source_post_id) : '';
        if ($detected_source_language) {
            $source_language = $detected_source_language;
        }
        pll_set_post_language($source_post_id, $source_language);
        pll_set_post_language($translated_post_id, $target_language);

        if (function_exists('pll_save_post_translations')) {
            $translations = function_exists('pll_get_post_translations') ? pll_get_post_translations($source_post_id) : [];
            $translations[$source_language] = $source_post_id;
            $translations[$target_language] = $translated_post_id;
            pll_save_post_translations($translations);
        }
        return 'polylang';
    }

    if (($mode === 'auto' || $mode === 'wpml') && (has_filter('wpml_element_type') || defined('ICL_SITEPRESS_VERSION'))) {
        $element_type = apply_filters('wpml_element_type', $post_type);
        $source_details = apply_filters('wpml_element_language_details', null, [
            'element_id' => $source_post_id,
            'element_type' => $element_type,
        ]);
        $trid = is_object($source_details) && !empty($source_details->trid) ? $source_details->trid : false;
        if (!$trid) {
            do_action('wpml_set_element_language_details', [
                'element_id' => $source_post_id,
                'element_type' => $element_type,
                'trid' => false,
                'language_code' => $source_language,
            ]);
            $source_details = apply_filters('wpml_element_language_details', null, [
                'element_id' => $source_post_id,
                'element_type' => $element_type,
            ]);
            $trid = is_object($source_details) && !empty($source_details->trid) ? $source_details->trid : false;
        }

        do_action('wpml_set_element_language_details', [
            'element_id' => $translated_post_id,
            'element_type' => $element_type,
            'trid' => $trid,
            'language_code' => $target_language,
            'source_language_code' => $source_language,
        ]);
        return 'wpml';
    }

    return 'none';
}

function translator_app_supported_post_types(): array {
    $post_types = get_post_types(['show_ui' => true], 'names');
    return array_values(array_diff($post_types, ['attachment', 'revision', 'nav_menu_item', 'custom_css', 'customize_changeset', 'wp_block']));
}

function translator_app_is_supported_post_type(string $post_type): bool {
    return in_array($post_type, translator_app_supported_post_types(), true);
}

function translator_app_resolve_translated_post_status(WP_Post $source_post): string {
    $status = get_option('translator_app_translated_post_status', 'draft');
    return $status === 'same_status' ? $source_post->post_status : $status;
}

function translator_app_sanitize_language_code($value): string {
    return strtolower(preg_replace('/[^a-zA-Z0-9_-]/', '', (string) $value));
}

function translator_app_sanitize_provider($value): string {
    $value = strtolower(sanitize_key((string) $value));
    return in_array($value, ['', 'nllb', 'openai', 'gemini', 'libretranslate', 'demo'], true) ? $value : '';
}

function translator_app_sanitize_publish_mode($value): string {
    return in_array($value, ['create_post', 'meta_only'], true) ? $value : 'create_post';
}

function translator_app_sanitize_post_status($value): string {
    return in_array($value, ['draft', 'pending', 'private', 'publish', 'same_status'], true) ? $value : 'draft';
}

function translator_app_sanitize_language_integration($value): string {
    return in_array($value, ['auto', 'polylang', 'wpml', 'none'], true) ? $value : 'auto';
}

function translator_app_sanitize_checkbox($value): string {
    return $value ? '1' : '0';
}
